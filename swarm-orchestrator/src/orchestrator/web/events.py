"""Async pub/sub event bus used to fan out updates to WebSocket subscribers."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class Event:
    """A single event broadcast to subscribers.

    `type` is a short dotted namespace like ``round.phase``, ``message.received``,
    ``summary.created``, ``federation.inbound``, ``log``.
    """

    type: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "data": self.data, "timestamp": self.timestamp}


class EventBus:
    """In-process async broadcaster.

    Maintains a bounded ring buffer of recent events so a freshly-connected
    WebSocket client can replay them before subscribing to the live stream.
    """

    def __init__(self, history_size: int = 200, queue_size: int = 256) -> None:
        self._history: deque[Event] = deque(maxlen=history_size)
        self._subscribers: set[asyncio.Queue[Event]] = set()
        self._queue_size = queue_size
        self._lock = asyncio.Lock()

    @property
    def history(self) -> list[Event]:
        return list(self._history)

    async def publish(self, type_: str, **data: Any) -> None:
        event = Event(type=type_, data=data)
        self._history.append(event)

        # Fan out to subscribers. If a subscriber's queue is full (slow
        # consumer), drop the event for that subscriber rather than blocking
        # the publisher — a lagging client should never stall the orchestrator.
        dropped = 0
        async with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dropped += 1
        if dropped:
            log.debug("events.dropped", type=type_, slow_subscribers=dropped)

    def publish_nowait(self, type_: str, **data: Any) -> None:
        """Synchronous variant for use from non-async callers.

        Appends to history immediately and best-effort fans out to subscribers.
        Safe to call from within an event loop even when not awaited.
        """
        event = Event(type=type_, data=data)
        self._history.append(event)
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    async def subscribe(self) -> asyncio.Queue[Event]:
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue[Event]) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)
