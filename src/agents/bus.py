"""A tiny async event bus.

The orchestrator and agents push events (status changes, streamed thinking/text,
tool calls, inter-agent messages) onto one queue; the SSE endpoint drains it and
forwards each event to the browser.
"""
import asyncio
import time


class EventBus:
    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    async def emit(self, event_type: str, **data) -> None:
        await self.queue.put({"type": event_type, "ts": time.time(), **data})

    async def close(self) -> None:
        await self.queue.put(None)  # sentinel: stops the SSE generator
