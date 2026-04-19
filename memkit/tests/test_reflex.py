"""Tests for the reflex layer — ring buffer semantics."""
import pytest

from memkit.layers.reflex import RingReflexStore


def test_empty_current_returns_empty_dict():
    r = RingReflexStore(capacity=4)
    assert r.current() == {}


def test_snapshot_and_current():
    r = RingReflexStore(capacity=4)
    r.snapshot({"pose": (1, 2, 3)})
    assert r.current() == {"pose": (1, 2, 3)}


def test_ring_overwrites_oldest():
    r = RingReflexStore(capacity=3)
    for i in range(5):
        r.snapshot({"i": i})
    assert len(r) == 3
    assert r.current() == {"i": 4}
    recent = r.recent(10)
    assert [s["i"] for s in recent] == [2, 3, 4]


def test_recent_zero_returns_empty():
    r = RingReflexStore(capacity=4)
    r.snapshot({"a": 1})
    assert r.recent(0) == []
    assert r.recent(-1) == []


def test_recent_more_than_buffer():
    r = RingReflexStore(capacity=8)
    r.snapshot({"a": 1})
    r.snapshot({"a": 2})
    assert r.recent(100) == [{"a": 1}, {"a": 2}]


def test_capacity_zero_rejected():
    with pytest.raises(ValueError):
        RingReflexStore(capacity=0)


def test_snapshot_does_not_share_reference():
    """Mutating the original dict after snapshot must not affect stored state."""
    r = RingReflexStore(capacity=4)
    state = {"a": 1}
    r.snapshot(state)
    state["a"] = 999
    assert r.current()["a"] == 1
