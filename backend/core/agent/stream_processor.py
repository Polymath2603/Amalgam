"""
Emotion tag stream processor — parses [emotion] tags from LLM responses.
Source: ChatVRM's emotion-tag system — the LLM declares its own emotional performance.
Tags are stripped from displayed text. Emotions are fired as WebSocket events.
"""
import re
from typing import AsyncGenerator, Callable, Awaitable

TAG_PATTERN = re.compile(r'\[(\w+)\]')

VALID_EMOTIONS = {
    "neutral", "joy", "angry", "sad", "relaxed", "surprised",
    "thinking", "shy", "excited", "confident", "tired", "scared",
    "bored", "loving",
}


async def parse_emotion_stream(
    raw_chunks: AsyncGenerator[str, None],
    on_emotion: Callable[[str], Awaitable[None]],
    emotion_mode: str = "tags",
) -> AsyncGenerator[str, None]:
    """
    Wraps a raw LLM stream. Strips emotion tags, fires on_emotion callbacks.

    raw_chunks: the LLM response chunks
    on_emotion: async fn(emotion_name: str) — called when a tag is found
    emotion_mode: if "tools", pass through unchanged (tags not expected)
    """
    if emotion_mode != "tags":
        async for chunk in raw_chunks:
            yield chunk
        return

    buffer = ""
    async for chunk in raw_chunks:
        buffer += chunk
        while True:
            match = TAG_PATTERN.search(buffer)
            if not match:
                break
            if match.start() > 0:
                yield buffer[:match.start()]
            emotion = match.group(1).lower()
            if emotion in VALID_EMOTIONS:
                await on_emotion(emotion)
            buffer = buffer[match.end():]
        if len(buffer) > 10:
            yield buffer[:-10]
            buffer = buffer[-10:]

    if buffer:
        cleaned = TAG_PATTERN.sub("", buffer)
        if cleaned:
            yield cleaned
