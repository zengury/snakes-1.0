"""Tests for episodic stores — both in-memory and SQLite."""
import time

import pytest

from memkit import Event, Outcome
from memkit.layers.episodic import InMemoryEpisodicStore
from memkit.stores.sqlite import SQLiteEpisodicStore


@pytest.fixture(params=["memory", "sqlite"])
def store(request, tmp_path):
    if request.param == "memory":
        yield InMemoryEpisodicStore()
    else:
        s = SQLiteEpisodicStore(tmp_path / "ep.db")
        yield s
        s.close()


def test_start_episode_returns_active(store):
    ep = store.start_episode("task_1")
    assert ep.episode_id.startswith("ep_")
    assert ep.task_id == "task_1"
    assert ep.outcome == Outcome.UNKNOWN
    assert store.get_episode(ep.episode_id) is not None


def test_append_events(store):
    ep = store.start_episode("task_1")
    store.append_event(ep.episode_id, Event(t=0.1, kind="cmd_issued", payload={"x": 1}))
    store.append_event(ep.episode_id, Event(t=0.2, kind="cmd_result", payload={"ok": True}))
    fresh = store.get_episode(ep.episode_id)
    assert len(fresh.events) == 2
    assert fresh.events[0].kind == "cmd_issued"
    assert fresh.events[1].payload["ok"] is True


def test_end_episode_sets_outcome(store):
    ep = store.start_episode("task_1")
    ended = store.end_episode(ep.episode_id, Outcome.SUCCESS, ["flag_a"])
    assert ended.outcome == Outcome.SUCCESS
    assert ended.anomaly_flags == ["flag_a"]


def test_cannot_append_to_ended_episode(store):
    ep = store.start_episode("task_1")
    store.end_episode(ep.episode_id, Outcome.SUCCESS)
    with pytest.raises(RuntimeError):
        store.append_event(ep.episode_id, Event(t=0, kind="x", payload={}))


def test_active_episodes(store):
    ep1 = store.start_episode("t1")
    ep2 = store.start_episode("t2")
    active = store.active_episodes()
    assert {e.episode_id for e in active} == {ep1.episode_id, ep2.episode_id}

    store.end_episode(ep1.episode_id, Outcome.SUCCESS)
    active = store.active_episodes()
    assert {e.episode_id for e in active} == {ep2.episode_id}


def test_unknown_episode_get_returns_none(store):
    assert store.get_episode("ep_missing") is None


def test_append_to_unknown_episode_raises(store):
    with pytest.raises(KeyError):
        store.append_event("ep_missing", Event(t=0, kind="x", payload={}))


def test_evict_completed(store):
    ep1 = store.start_episode("t1")
    store.end_episode(ep1.episode_id, Outcome.SUCCESS)
    # Evict with very short TTL
    time.sleep(0.05)
    evicted = store.evict_completed(older_than_seconds=0.01)
    assert evicted == 1
    assert store.get_episode(ep1.episode_id) is None


def test_evict_leaves_active_alone(store):
    ep_active = store.start_episode("t_active")
    ep_done = store.start_episode("t_done")
    store.end_episode(ep_done.episode_id, Outcome.SUCCESS)
    time.sleep(0.05)
    store.evict_completed(older_than_seconds=0.01)
    assert store.get_episode(ep_active.episode_id) is not None
    assert store.get_episode(ep_done.episode_id) is None
