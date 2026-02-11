"""Tests for PushSubscriptionStore (JSON file backend)."""

import json

import pytest

from agentdeck.notifications.store import (
    PushSubscriptionStore,
)


@pytest.fixture
def store(tmp_path):
    return PushSubscriptionStore(tmp_path / "subs.json")


class TestSubscribe:
    def test_subscribe_persists(self, store, tmp_path):
        store.subscribe("https://ep/1", "key1", "auth1", "s1")
        data = json.loads((tmp_path / "subs.json").read_text())
        assert len(data) == 1
        assert data[0]["endpoint"] == "https://ep/1"
        assert data[0]["session_id"] == "s1"

    def test_upsert_replaces(self, store):
        store.subscribe("https://ep/1", "k1", "a1", "s1")
        store.subscribe("https://ep/1", "k2", "a2", "s1")
        subs = store.get_subscriptions_for_session("s1")
        assert len(subs) == 1
        assert subs[0].p256dh == "k2"

    def test_multi_session_same_endpoint(self, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        store.subscribe("https://ep/1", "k", "a", "s2")
        assert len(store.get_subscriptions_for_session("s1")) == 1
        assert len(store.get_subscriptions_for_session("s2")) == 1
        ids = store.get_session_ids_for_endpoint("https://ep/1")
        assert set(ids) == {"s1", "s2"}


class TestUnsubscribe:
    def test_unsubscribe_removes(self, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        store.unsubscribe("https://ep/1", "s1")
        assert store.get_subscriptions_for_session("s1") == []

    def test_unsubscribe_noop_if_missing(self, store):
        store.unsubscribe("https://ep/1", "s1")
        assert store.get_subscriptions_for_session("s1") == []


class TestRemoveEndpoint:
    def test_removes_all_sessions(self, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        store.subscribe("https://ep/1", "k", "a", "s2")
        store.remove_endpoint("https://ep/1")
        assert store.get_session_ids_for_endpoint("https://ep/1") == []


class TestReload:
    def test_reload_from_disk(self, tmp_path):
        store1 = PushSubscriptionStore(tmp_path / "subs.json")
        store1.subscribe("https://ep/1", "k", "a", "s1")

        store2 = PushSubscriptionStore(tmp_path / "subs.json")
        assert len(store2.get_subscriptions_for_session("s1")) == 1

    def test_corrupt_file_loads_empty(self, tmp_path):
        path = tmp_path / "subs.json"
        path.write_text("not json")
        store = PushSubscriptionStore(path)
        assert store.get_session_ids_for_endpoint("x") == []
