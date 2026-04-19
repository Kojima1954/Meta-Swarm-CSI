"""Tests for the EventBus pub/sub used by the web layer."""

from __future__ import annotations

import asyncio

import pytest

from orchestrator.web.events import Event, EventBus


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_appends_to_history(self) -> None:
        bus = EventBus(history_size=5)
        await bus.publish("round.phase", phase="DISCUSS", round=1)
        assert len(bus.history) == 1
        evt = bus.history[0]
        assert isinstance(evt, Event)
        assert evt.type == "round.phase"
        assert evt.data == {"phase": "DISCUSS", "round": 1}

    @pytest.mark.asyncio
    async def test_history_is_bounded(self) -> None:
        bus = EventBus(history_size=3)
        for i in range(10):
            await bus.publish("tick", n=i)
        assert len(bus.history) == 3
        assert [e.data["n"] for e in bus.history] == [7, 8, 9]

    @pytest.mark.asyncio
    async def test_subscribe_receives_future_events(self) -> None:
        bus = EventBus()
        q = await bus.subscribe()
        await bus.publish("round.phase", phase="DISCUSS", round=1)
        evt = await asyncio.wait_for(q.get(), timeout=1.0)
        assert evt.type == "round.phase"
        assert evt.data["round"] == 1
        await bus.unsubscribe(q)

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self) -> None:
        bus = EventBus()
        q = await bus.subscribe()
        await bus.unsubscribe(q)
        await bus.publish("test", val=1)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(q.get(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_multiple_subscribers_each_get_event(self) -> None:
        bus = EventBus()
        q1 = await bus.subscribe()
        q2 = await bus.subscribe()
        assert bus.subscriber_count == 2

        await bus.publish("broadcast", ok=True)

        e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        e2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        assert e1.type == "broadcast"
        assert e2.type == "broadcast"

    @pytest.mark.asyncio
    async def test_slow_subscriber_does_not_block_publisher(self) -> None:
        """If a subscriber's queue fills, publish should not block."""
        bus = EventBus(queue_size=2)
        q = await bus.subscribe()

        # Publish more events than the queue can hold
        for i in range(10):
            await bus.publish("spam", i=i)

        # publisher didn't hang; subscriber gets at most queue_size events
        received = 0
        while not q.empty():
            await q.get()
            received += 1
        assert received <= 2

    @pytest.mark.asyncio
    async def test_event_to_dict_shape(self) -> None:
        evt = Event(type="foo", data={"x": 1})
        d = evt.to_dict()
        assert d["type"] == "foo"
        assert d["data"] == {"x": 1}
        assert "timestamp" in d
