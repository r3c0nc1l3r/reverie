"""Bounded live delivery primitives used by the dashboard WebSocket server.

The dashboard deliberately keeps this module independent from aiohttp.  That makes the
slow-viewer policy easy to test and keeps browser state collection out of request handlers.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field


@dataclass(eq=False)
class ViewerBuffer:
    """A bounded viewer queue with lossless events until a resync is required.

    Browser frames and other live state are replaceable: only the most recent update for
    a run matters.  Coordination events are ordered; when a viewer cannot keep up, the
    queue is discarded and the sender is told to produce a fresh snapshot.
    """

    event_limit: int = 64
    _events: deque = field(default_factory=deque, init=False)
    _live: dict = field(default_factory=dict, init=False)
    _resync: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _condition: asyncio.Condition = field(default_factory=asyncio.Condition, init=False)

    async def put_event(self, message):
        async with self._condition:
            if self._closed:
                return
            if len(self._events) >= self.event_limit:
                self._events.clear()
                self._live.clear()
                self._resync = True
            elif not self._resync:
                self._events.append(message)
            self._condition.notify()

    async def put_live(self, run_id, message):
        async with self._condition:
            if not self._closed and not self._resync:
                key = run_id or ""
                if key not in self._live and len(self._live) >= max(1, self.event_limit):
                    self._live.pop(next(iter(self._live)))
                self._live[key] = message
                self._condition.notify()

    async def put_control(self, message):
        """Queue a small protocol message in order with coordination events."""
        await self.put_event(message)

    async def get(self):
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._closed or self._resync or self._events or self._live
            )
            if self._closed:
                return None
            if self._resync:
                self._resync = False
                return {"type": "resync_required", "reason": "slow_viewer"}
            if self._events:
                return self._events.popleft()
            _, message = self._live.popitem()
            return message

    async def close(self):
        async with self._condition:
            self._closed = True
            self._events.clear()
            self._live.clear()
            self._condition.notify_all()

    @property
    def pending(self):
        return len(self._events) + len(self._live) + int(self._resync)


def newer_revision(message, previous):
    """Return an integer revision only when it advances the client's state."""
    try:
        revision = int(message.get("revision", 0))
    except (TypeError, ValueError):
        return None
    return revision if revision > previous else None
