"""Stream processing — typed delta chunks and event emission."""

import json
import re
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional, Union


class DeltaTag(Enum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"
    DONE = "done"
    META = "meta"


class StreamProcessor:
    """Parses raw LLM stream output into typed deltas."""

    _TAG_PATTERN = re.compile(r"<(\w+)>(.*?)</\1>", re.DOTALL)

    @staticmethod
    def process(raw: str) -> List[Dict[str, Any]]:
        """Split a raw string into a list of tagged deltas.

        Each delta has ``tag`` (DeltaTag) and ``data``.
        Untagged text is tagged as TEXT.
        """
        deltas: List[Dict[str, Any]] = []
        pos = 0

        for m in StreamProcessor._TAG_PATTERN.finditer(raw):
            # Text before this tag
            if m.start() > pos:
                text = raw[pos:m.start()].strip()
                if text:
                    deltas.append({"tag": DeltaTag.TEXT, "data": text})

            tag_name = m.group(1).lower()
            content = m.group(2).strip()

            try:
                tag = DeltaTag(tag_name)
            except ValueError:
                tag = DeltaTag.TEXT

            if tag == DeltaTag.TOOL_CALL:
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    data = {"raw": content}
            else:
                data = content

            deltas.append({"tag": tag, "data": data})
            pos = m.end()

        # Remaining text
        remaining = raw[pos:].strip()
        if remaining:
            deltas.append({"tag": DeltaTag.TEXT, "data": remaining})

        if not deltas:
            deltas.append({"tag": DeltaTag.TEXT, "data": raw})

        return deltas

    @staticmethod
    async def stream_deltas(raw_stream: AsyncIterator[str]) -> AsyncIterator[Dict[str, Any]]:
        """Wrap a raw string stream, yielding typed delta dicts."""
        buffer = ""
        async for chunk in raw_stream:
            buffer += chunk
            # Emit complete tags as they arrive
            while True:
                m = StreamProcessor._TAG_PATTERN.search(buffer)
                if not m:
                    break
                # Emit any text before the match
                if m.start() > 0:
                    prefix = buffer[:m.start()].strip()
                    if prefix:
                        yield {"tag": DeltaTag.TEXT, "data": prefix}
                tag_name = m.group(1).lower()
                content = m.group(2).strip()
                try:
                    tag = DeltaTag(tag_name)
                except ValueError:
                    tag = DeltaTag.TEXT
                yield {"tag": tag, "data": content}
                buffer = buffer[m.end():]
            # Emit dangling text as provisional TEXT
            if buffer.strip():
                yield {"tag": DeltaTag.TEXT, "data": buffer}
                buffer = ""
        if buffer.strip():
            yield {"tag": DeltaTag.TEXT, "data": buffer}
        yield {"tag": DeltaTag.DONE, "data": None}
