import re
from collections.abc import AsyncIterator

_BOUNDARY = re.compile(r"[.!?]+\s")


async def sentences(deltas: AsyncIterator[str]) -> AsyncIterator[str]:
    """Group streamed text deltas into whole sentences so TTS can start before the reply is complete.

    A boundary needs trailing whitespace, so decimals like "2.5" are not split; the tail is flushed at the end.
    """
    buffer = ""
    async for delta in deltas:
        buffer += delta
        while (match := _BOUNDARY.search(buffer)) is not None:
            sentence = buffer[: match.end()].strip()
            buffer = buffer[match.end() :]
            if sentence:
                yield sentence
    if buffer.strip():
        yield buffer.strip()
