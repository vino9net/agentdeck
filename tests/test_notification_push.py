"""Tests for PushNotifier state-change detection."""

from unittest.mock import MagicMock, patch

import pytest

from agentdeck.notifications.push import PushNotifier
from agentdeck.notifications.store import (
    PushSubscriptionStore,
)
from agentdeck.sessions.models import UIState


@pytest.fixture
def store(tmp_path):
    return PushSubscriptionStore(tmp_path / "subs.json")


@pytest.fixture
def notifier(store, tmp_path):
    # Use a dummy key path — we mock webpush anyway
    return PushNotifier(
        store=store,
        vapid_private_key_path=tmp_path / "fake.pem",
        vapid_claims={"sub": "mailto:test@test"},
    )


URL = "https://app.example.com"


class TestStateTransition:
    def test_working_to_prompt_notifies(self, notifier, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        notifier.check_and_notify("s1", UIState.WORKING, URL)
        with patch("agentdeck.notifications.push.webpush") as mock:
            sent = notifier.check_and_notify("s1", UIState.PROMPT, URL)
        assert sent == 1
        mock.assert_called_once()

    def test_same_state_no_repeat(self, notifier, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        with patch("agentdeck.notifications.push.webpush"):
            notifier.check_and_notify("s1", UIState.PROMPT, URL)
        with patch("agentdeck.notifications.push.webpush") as mock:
            sent = notifier.check_and_notify("s1", UIState.PROMPT, URL)
        assert sent == 0
        mock.assert_not_called()

    def test_working_state_no_notify(self, notifier, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        with patch("agentdeck.notifications.push.webpush") as mock:
            sent = notifier.check_and_notify("s1", UIState.WORKING, URL)
        assert sent == 0
        mock.assert_not_called()

    def test_no_subscribers_no_notify(self, notifier):
        with patch("agentdeck.notifications.push.webpush") as mock:
            sent = notifier.check_and_notify("s1", UIState.PROMPT, URL)
        assert sent == 0
        mock.assert_not_called()

    def test_selection_state_notifies(self, notifier, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        notifier.check_and_notify("s1", UIState.WORKING, URL)
        with patch("agentdeck.notifications.push.webpush") as mock:
            sent = notifier.check_and_notify("s1", UIState.SELECTION, URL)
        assert sent == 1
        mock.assert_called_once()


class TestForgetSession:
    def test_forget_resets_state(self, notifier, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        with patch("agentdeck.notifications.push.webpush"):
            notifier.check_and_notify("s1", UIState.PROMPT, URL)
        notifier.forget_session("s1")
        # After forget, same state should trigger again
        with patch("agentdeck.notifications.push.webpush") as mock:
            sent = notifier.check_and_notify("s1", UIState.PROMPT, URL)
        assert sent == 1
        mock.assert_called_once()


class TestEndpointCleanup:
    def test_410_removes_endpoint(self, notifier, store):
        store.subscribe("https://ep/1", "k", "a", "s1")
        notifier.check_and_notify("s1", UIState.WORKING, URL)

        exc = _make_webpush_exc(410)
        with patch(
            "agentdeck.notifications.push.webpush",
            side_effect=exc,
        ):
            sent = notifier.check_and_notify("s1", UIState.PROMPT, URL)
        assert sent == 0
        assert store.get_subscriptions_for_session("s1") == []


def _make_webpush_exc(status_code):
    from pywebpush import WebPushException

    resp = MagicMock()
    resp.status_code = status_code
    return WebPushException("gone", response=resp)
