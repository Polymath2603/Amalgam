"""Legacy monolithic Agent — kept for backwards compatibility.

Phase 3 new agent types (BasicAgent, ReflectiveAgent, PlanningAgent)
are in sibling modules.  This module is the original Agent class that
wires LLM, Memory, ContextBuilder, and MCP together.
"""
import asyncio
import json
import logging
import re
from typing import AsyncIterator, Union, Tuple, List, Dict

from backend.core.memory import Memory
from backend.core.context_builder import ContextBuilder
from backend.core.llm import LLMRouter
from backend.core.plugin import get_registry as get_plugin_registry
from backend.core.utils.tokens import estimate_message_list_tokens, estimate_tokens, truncate_to_token_limit

logger = logging.getLogger(__name__)

THINK_RE = re.compile(r'<think>(.*?)</think>', re.DOTALL)


async def execute_tool_safe(mcp_client, tool_name: str, tool_args: dict,
                            plugins, logger) -> tuple:
    """
    Execute one tool call safely — catches exceptions so one failure
    doesn't stop all other parallel calls from completing.
    """
    try:
        result = "No MCP client"
        if mcp_client:
            result = await mcp_client.call_tool(tool_name, tool_args)
        result = await plugins.hook_tool_result(tool_name, tool_args, result)
        return (tool_name, tool_args, result, None)
    except Exception as e:
        logger.warning(f"Tool '{tool_name}' failed: {e}")
        return (tool_name, tool_args, f"Tool error: {str(e)}", str(e))

_LEGACY_EMOTION_RE = re.compile(r'/\[\[.*?\]\]', re.IGNORECASE)
_LEGACY_EXPRESSION_RE = re.compile(r'/\(\(.*?\)\)', re.IGNORECASE)
_LEGACY_ACTION_RE = re.compile(r'/\*\*(.+?)\*\*/?', re.DOTALL)


class Agent:
    def __init__(self, mcp_client=None, llm=None, memory=None, context_builder=None, settings=None, strategy_selector=None):
        self.settings = settings
        self.llm = llm or LLMRouter(settings=settings)
        self.memory = memory or Memory(llm_router=self.llm)
        self.context_builder = context_builder or ContextBuilder(settings=settings)
        self.mcp_client = mcp_client
        self.strategy_selector = strategy_selector

    def update_emotion_tags(self, tags):
        pass

    def update_expression_names(self, names):
        pass

    def update_settings(self, settings):
        self.settings = settings
        self.context_builder.settings = settings

    def _process_tags(self, text: str):
        for m in THINK_RE.finditer(text):
            yield ('__thinking__', m.group(1).strip())
        for m in _LEGACY_ACTION_RE.finditer(text):
            content = m.group(1).strip()
            if content:
                yield ('__roleplay__', content)

    def _strip_all_tags(self, text: str) -> str:
        text = THINK_RE.sub('', text)
        text = _LEGACY_ACTION_RE.sub('', text)
        text = _LEGACY_EMOTION_RE.sub('', text)
        text = _LEGACY_EXPRESSION_RE.sub('', text)
        text = re.sub(r'/\*\*.*?\*\*/?', '', text, flags=re.DOTALL)
        text = re.sub(r'/\*.*?\*/', '', text, flags=re.DOTALL)
        text = re.sub(r'/\[\[.*?\]\]', '', text)
        text = re.sub(r'/\(\(.*?\)\)', '', text)
        text = re.sub(r'\[\[.*?\]\]', '', text)
        text = re.sub(r'\(\(.*?\)\)', '', text)
        text = re.sub(r'/\*\*.*', '', text)
        text = re.sub(r'\s*/\s*$', '', text)
        return text.strip()

    def _clean_remaining_tags(self, text: str) -> str:
        text = re.sub(r'/\[\[[^\]\s]*', '', text)
        text = re.sub(r'/\(\([^\)\s]*', '', text)
        text = re.sub(r'\[\[[^\]\s]*', '', text)
        text = re.sub(r'\(\([^\)\s]*', '', text)
        text = re.sub(r'/\*\*.*', '', text)
        text = re.sub(r'\s*/\s*$', '', text)
        return text.strip()

    async def spawn_subagent(self, prompt: str, session_id: str = None) -> str:
        sub_memory = Memory(llm_router=self.llm)
        if not session_id:
            sub_memory.start_session()
        else:
            sub_memory.set_current_session(session_id)
        sub_agent = Agent(
            mcp_client=self.mcp_client,
            llm=self.llm,
            memory=sub_memory,
            context_builder=ContextBuilder(settings=self.settings),
            settings=self.settings,
        )
        parts = []
        async for chunk in sub_agent.handle_user_input(prompt):
            if isinstance(chunk, str):
                parts.append(chunk)
        return "".join(parts)

    def _estimate_tokens(self, messages: List[Dict], tools: List[Dict] = None, model: str = None) -> int:
        total = estimate_message_list_tokens(messages, model=model)
        if tools:
            total += estimate_tokens(json.dumps(tools), model=model)
        return total + 1

    def _truncate_context(self, messages: List[Dict], max_tokens: int, tools: List[Dict] = None, model: str = None) -> List[Dict]:
        if not messages:
            return []
        system = messages[0]
        history = messages[1:]

        while self._estimate_tokens([system] + history, tools, model=model) > max_tokens and len(history) > 1:
            history.pop(0)

        if self._estimate_tokens([system] + history, tools, model=model) > max_tokens:
            sys_str = str(system.get("content", ""))
            tools_tokens = estimate_tokens(json.dumps(tools), model=model) if tools else 0
            history_tokens = estimate_message_list_tokens(history, model=model)
            sys_budget = max_tokens - tools_tokens - history_tokens - 20

            if sys_budget > 0:
                truncated = truncate_to_token_limit(sys_str, sys_budget, model=model)
                system = system.copy()
                system["content"] = truncated + "\n\n...[System Prompt Truncated to fit Context]..."
                logger.debug(f"System prompt truncated to {sys_budget} tokens to fit budget")
            else:
                fallback_budget = 300
                truncated = truncate_to_token_limit(sys_str, fallback_budget, model=model)
                system = system.copy()
                system["content"] = truncated + "\n\n...[System Prompt HEAVILY Truncated due to large Tools/History payload]..."
                logger.warning(f"Token budget exceeded by tools/history! System prompt heavily truncated to {fallback_budget} tokens.")

        return [system] + history

    async def generate_idle_prompt(self) -> str:
        char_id = self.settings.get("character.active", "default") if self.settings else "default"
        chars = self.context_builder._characters
        char = chars.get(char_id, {})
        name = char.get("name", "the assistant")
        personality = char.get("personality", "")
        vocabulary = char.get("vocabulary", [])

        prompt = f"You are {name}."
        if personality:
            prompt += f" Your personality: {personality}."
        if vocabulary:
            prompt += f" Your signature phrases include: {', '.join(vocabulary[:3])}."
        prompt += (
            " Generate a brief, natural conversation starter or idle observation."
            " Keep it under 20 words. Be in-character. Just the text, no quotes."
        )

        try:
            result = await self.llm.generate([{"role": "user", "content": prompt}], temperature=0.9)
            return (result or "").strip().strip('"').strip("'")
        except Exception as e:
            logger.warning(f"Idle prompt generation failed: {e}")
            return ""

    async def subconscious_reflect(self) -> str:
        recent = self.memory.get_recent(10)
        if not recent:
            return ""

        chat_log = "\n".join(f"{m['role']}: {m['content']}" for m in recent)
        char_id = self.settings.get("character.active", "default") if self.settings else "default"
        chars = self.context_builder._characters
        char = chars.get(char_id, {})
        name = char.get("name", "the assistant")

        prompt = (
            f"You are {name}. Summarize the key facts and emotional undertones "
            f"from this recent conversation in one sentence. Focus on what you learned "
            f"about the user and how they feel.\n\nConversation:\n{chat_log}"
        )

        try:
            summary = await self.llm.generate([{"role": "user", "content": prompt}], temperature=0.5)
            if summary:
                await self.memory.add_turn("system", f"[reflection] {summary.strip()}")
            return summary.strip() if summary else ""
        except Exception as e:
            logger.warning(f"Subconscious reflection failed: {e}")
            return ""

    @staticmethod
    def _classify_intent(text: str) -> str:
        """Simple keyword-based intent classification for strategy selection."""
        text_lower = text.lower().strip()
        if any(text_lower.startswith(p) for p in ("what is", "what are", "who is", "when is",
                                                    "where is", "how much", "tell me about",
                                                    "define", "what does", "why")):
            return "conversation"
        if any(kw in text_lower for kw in ("remember", "do you remember", "recall", "what did i",
                                            "what was", "earlier", "previously", "before")):
            return "memory_op"
        if any(kw in text_lower for kw in ("search vault", "find in vault", "vault search",
                                            "access vault", "open vault")):
            return "vault_op"
        if any(kw in text_lower for kw in ("code", "function", "class ", "def ", "implement",
                                            "debug", "fix ", "bug", "refactor")):
            return "code"
        if any(kw in text_lower for kw in ("reflect", "think about", "analyze", "evaluate",
                                            "consider")):
            return "reflection"
        return "tool_execution"  # default for action-oriented requests

    async def handle_user_input(self, text: str, images: list = None, relationship_context: str = "") -> AsyncIterator[Union[str, Tuple[str, str]]]:
        await self.memory.add_turn("user", text)

        if self.mcp_client is not None and self.mcp_client.has_servers():
            await self.mcp_client.wait_for_tools(timeout=8.0, min_tools=1)

        # Intent classification & strategy selection
        intent = self._classify_intent(text)
        strategy = None
        if self.strategy_selector:
            strategy = self.strategy_selector.select(intent)
            logger.debug("Strategy for intent=%s: max_iterations=%s, temperature=%s, CoT=%s",
                         intent, strategy.max_iterations, strategy.temperature, strategy.use_chain_of_thought)
        max_iterations = strategy.max_iterations if strategy else 5

        iterations = 0
        current_input = text
        native_tools = self.llm.supports_native_tools()
        last_tool_call = None
        _pending_tool_announce = []

        while iterations < max_iterations:
            iterations += 1
            _flushed_this_iter = False

            tools = self.mcp_client.get_tool_schema() if self.mcp_client else []
            history = self.memory.get_recent()
            summary = self.memory.get_summary()
            relevant = await self.memory.get_relevant(current_input)

            character_id = None
            additional_prompt = ""
            max_tokens = 8192
            if self.settings:
                character_id = self.settings.get("character.active", "default")
                additional_prompt = self.settings.get("character.system_prompt", "")

            max_tokens = self.llm.get_context_token_limit()

            plugins = get_plugin_registry()
            tools = await plugins.hook_tool_definition(tools)
            messages = self.context_builder.build(
                tools, history, current_input,
                character_id=character_id,
                additional_prompt=additional_prompt,
                summary=summary,
                relevant=relevant,
                relationship_context=relationship_context,
                native_tools_available=native_tools,
            )

            out_tokens = self.llm.get_max_output_tokens()
            model_name = self.llm.get_model_name() if hasattr(self.llm, 'get_model_name') else None
            available = max_tokens - out_tokens - 50
            messages = self._truncate_context(messages, max(available, 500), tools, model=model_name)

            est = self._estimate_tokens(messages, tools if native_tools else None, model=model_name)
            logger.debug(f"TOKEN BUDGET: model={model_name}, context_limit={max_tokens}, output={out_tokens}, available={available}, used={est}")
            messages = await plugins.hook_messages(messages)

            if images:
                last_text = messages[-1]["content"]
                if isinstance(last_text, str):
                    content = [{"type": "text", "text": last_text}]
                    for img in images:
                        content.append({"type": "image_url", "image_url": {"url": img}})
                    messages[-1]["content"] = content

            tool_called = False
            in_tool_block = False
            accumulated = ""
            _last_clean = ""

            try:
                if native_tools and tools:
                    # Phase 1: Collect all items from the LLM stream
                    collected_tool_calls = []
                    text_accumulated = ""
                    _pending_tool_announce = []
                    async for item in self.llm.stream_with_tools(messages, tools, temperature=strategy.temperature if strategy else None):

                        if isinstance(item, str):
                            if item.startswith("[Error:"):
                                yield ("__error__", item)
                                _pending_tool_announce.clear()
                                continue
                            text_accumulated += item

                        elif isinstance(item, dict) and item.get("type") == "tool_use":
                            tool_name = item["name"]
                            tool_args = item.get("arguments") or {}
                            tool_id = item.get("id", "")
                            tool_sig = (tool_name, frozenset(
                                (k, str(v)) for k, v in sorted(tool_args.items())))
                            if tool_sig == last_tool_call:
                                msg = f"Repeated identical tool call to {tool_name} — not retrying."
                                yield ("__error__", msg)
                                continue
                            last_tool_call = tool_sig
                            collected_tool_calls.append(item)
                            _pending_tool_announce.append(f"Calling tool: {tool_name}")

                    # Phase 2: Flush accumulated text
                    if text_accumulated.strip():
                        for msg in _pending_tool_announce:
                            yield ("__tool__", msg)
                        _pending_tool_announce = []

                        in_think = '<think>' in text_accumulated and '</think>' not in text_accumulated
                        if not in_think:
                            tags = list(self._process_tags(text_accumulated))
                            cleaned = self._strip_all_tags(text_accumulated)
                            for tag_type, tag_val in tags:
                                yield (tag_type, tag_val)
                            if cleaned.strip():
                                yield cleaned
                                await self.memory.add_turn("assistant", cleaned.strip())

                    # Phase 3: Execute all collected tool calls in parallel
                    if collected_tool_calls:
                        tool_called = True
                        results = await asyncio.gather(*[
                            execute_tool_safe(
                                self.mcp_client,
                                tc["name"],
                                tc.get("arguments") or {},
                                plugins,
                                logger,
                            )
                            for tc in collected_tool_calls
                        ], return_exceptions=False)

                        for (tool_name, tool_args, result, error) in results:
                            tool_id = next(
                                (tc.get("id", "") for tc in collected_tool_calls
                                 if tc["name"] == tool_name),
                                ""
                            )
                            if tool_name.startswith("avatar_"):
                                yield ("__avatar__", result)
                            if result.startswith("COMMAND_BLOCKED:"):
                                blocked_cmd = result[len("COMMAND_BLOCKED:"):]
                                yield ("__permission__", blocked_cmd)
                                _pending_tool_announce.append(
                                    f"Command blocked — needs permission: {blocked_cmd}")
                                current_input = f"Tool result for {tool_name}: BLOCKED — {blocked_cmd}"
                            else:
                                current_input = f"Tool result for {tool_name} (call_id={tool_id}): {result}"
                            await self.memory.add_turn("system", current_input)

                        # If multiple tool calls were made, collect results for next iteration
                        if len(collected_tool_calls) > 1:
                            combined_results = "\n".join(
                                f"--- {tc['name']} ---\n{result}"
                                for tc, (_, _, result, _) in zip(
                                    collected_tool_calls, results)
                            )
                            current_input = f"All tool results:\n{combined_results}"
                else:
                    tool_block_buf = ""
                    in_tool_block = False
                    async for token in self.llm.stream(messages, temperature=strategy.temperature if strategy else None):
                        if token.startswith("[Error:"):
                            yield ("__error__", token)
                            _pending_tool_announce.clear()
                            continue
                        if not _flushed_this_iter:
                            _flushed_this_iter = True
                            for msg in _pending_tool_announce:
                                yield ("__tool__", msg)
                            _pending_tool_announce = []
                        if not in_tool_block and "```tool" in accumulated + token + tool_block_buf:
                            in_tool_block = True
                            clean_before = self._strip_all_tags(accumulated).strip()
                            if clean_before:
                                await self.memory.add_turn("assistant", clean_before)
                            continue

                        if in_tool_block:
                            tool_block_buf += token
                            if "```\n" in tool_block_buf or tool_block_buf.endswith("```"):
                                try:
                                    start_idx = tool_block_buf.find("{")
                                    end_idx = tool_block_buf.rfind("}") + 1
                                    if start_idx != -1 and end_idx != -1:
                                        tool_call = json.loads(tool_block_buf[start_idx:end_idx])
                                        name = tool_call.get("name")
                                        args = tool_call.get("arguments") or {}
                                        tool_sig = (name, frozenset((k, str(v)) for k, v in sorted(args.items())))
                                        if tool_sig == last_tool_call:
                                            msg = f"Repeated identical tool call to {name} — not retrying. Respond based on the previous result."
                                            yield ("__error__", msg)
                                            current_input = msg
                                            await self.memory.add_turn("system", current_input)
                                            tool_called = True
                                            break
                                        last_tool_call = tool_sig
                                        _pending_tool_announce.append(f"Calling tool: {name}")
                                        result = "No MCP client"
                                        if self.mcp_client:
                                            result = await self.mcp_client.call_tool(name, args)
                                        result = await plugins.hook_tool_result(name, args, result)
                                        if name.startswith("avatar_"):
                                            yield ("__avatar__", result)
                                        if result.startswith("COMMAND_BLOCKED:"):
                                            blocked_cmd = result[len("COMMAND_BLOCKED:"):]
                                            yield ("__permission__", blocked_cmd)
                                            _pending_tool_announce.append(f"Command blocked — needs permission: {blocked_cmd}")
                                        current_input = f"Tool result for {name}: {result}"
                                        await self.memory.add_turn("system", current_input)
                                        tool_called = True
                                        break
                                except Exception as e:
                                    yield f"\n[Error parsing tool call: {e}]\n"
                                    current_input = f"Tool parse error: {e}"
                                    await self.memory.add_turn("system", current_input)
                                    tool_called = True
                                    break
                        else:
                            accumulated += token
                            in_think = '<think>' in accumulated and '</think>' not in accumulated
                            if in_think:
                                continue
                            tags = list(self._process_tags(accumulated))
                            cleaned = self._strip_all_tags(accumulated)
                            for tag_type, tag_val in tags:
                                yield (tag_type, tag_val)
                            if len(cleaned) > len(_last_clean):
                                yield cleaned[len(_last_clean):]
                            _last_clean = cleaned

                if not tool_called:
                    if accumulated.strip():
                        final_text = self._clean_remaining_tags(accumulated)
                        if _last_clean == "" and final_text:
                            yield final_text
                        await self.memory.add_turn("assistant", accumulated.strip())
                    break

            except Exception as e:
                logger.error(f"agent: stream exception: {type(e).__name__}: {e}")
                _pending_tool_announce.clear()
                yield ("__error__", str(e))
                if accumulated.strip():
                    await self.memory.add_turn("assistant", accumulated.strip())
                break
            finally:
                if in_tool_block and not tool_called:
                    logger.warning("agent: stream ended mid-tool-block")
                    in_tool_block = False

        for msg in _pending_tool_announce:
            yield ("__tool__", msg)
        _pending_tool_announce = []

        if iterations >= 5:
            yield "\n[Max tool iterations reached.]\n"

    async def stream_response(self, messages: List[Dict], settings: Dict) -> AsyncIterator[Union[Tuple[str, str], str]]:
        _ = settings
        session_id = self.context_builder._current_session
        self.memory.set_session(session_id)

        if self.context_builder._current_identity is None:
            self.context_builder._current_identity = self.context_builder.identity
            self.context_builder._current_character_name = None
            self.context_builder._current_character_style = ""

        system_prompt = self.context_builder.build()
        vault_context = self.memory.get_all_context(session_id)

        llm_messages = [{"role": "system", "content": system_prompt}]
        if vault_context and vault_context.strip():
            llm_messages.append({"role": "system", "content": vault_context})

        history_count = 0
        max_history = 20
        for m in reversed(messages):
            if history_count >= max_history * 2:
                break
            llm_messages.insert(1 if vault_context and vault_context.strip() else 1, m)
            history_count += 1

        response = self.mcp_client.call_llm_with_tools if self.mcp_client else None

        context = {"session_id": session_id, "settings": self.settings}
        response_text = ""

        if response:
            async for chunk in response(system_prompt, llm_messages, self.llm, settings):
                if isinstance(chunk, tuple) and chunk[0] == "__tool_call__":
                    yield chunk
                elif isinstance(chunk, str):
                    response_text += chunk
                    processed = self._strip_all_tags(response_text)
                    yield processed
                else:
                    yield chunk
        else:
            full_response = ""
            async for chunk in self.llm.stream_chat(messages=llm_messages, settings=settings):
                if isinstance(chunk, str):
                    full_response += chunk
                    yield chunk

            response_text = full_response

        response_text = await self._process_plugin_hooks(
            "post_stream", messages, response_text, context
        )

    async def generate_response(self, messages: List[Dict], settings: Dict) -> str:
        session_id = self.context_builder._current_session
        self.memory.set_session(session_id)

        if self.context_builder._current_identity is None:
            self.context_builder._current_identity = self.context_builder.identity
            self.context_builder._current_character_name = None
            self.context_builder._current_character_style = ""

        system_prompt = self.context_builder.build()
        vault_context = self.memory.get_all_context(session_id)

        llm_messages = [{"role": "system", "content": system_prompt}]
        if vault_context and vault_context.strip():
            llm_messages.append({"role": "system", "content": vault_context})

        history_count = 0
        max_history = 20
        for m in reversed(messages):
            if history_count >= max_history * 2:
                break
            llm_messages.insert(1 if vault_context and vault_context.strip() else 1, m)
            history_count += 1

        context = {"session_id": session_id, "settings": self.settings}
        response = await self.llm.chat(messages=llm_messages, settings=settings)
        response = await self._process_plugin_hooks("post_generate", messages, response, context)
        return response
