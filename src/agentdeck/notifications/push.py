"""Web Push notification delivery with state-change gating."""

import json
from pathlib import Path

import structlog
from pywebpush import WebPushException, webpush

from agentdeck.notifications.store import (
    PushSubscription,
    PushSubscriptionStore,
)
from agentdeck.sessions.models import UIState

logger = structlog.get_logger()

_NOTIFY_STATES = {UIState.PROMPT, UIState.SELECTION}


class PushNotifier:
    """Send push notifications on session state transitions.

    Only notifies when a session transitions INTO PROMPT or
    SELECTION from a different state. Duplicate states are
    suppressed.
    """

    def __init__(
        self,
        store: PushSubscriptionStore,
        vapid_private_key_path: Path,
        vapid_claims: dict,
    ) -> None:
        self._store = store
        self._private_key = str(vapid_private_key_path)
        self._claims = vapid_claims
        self._last_state: dict[str, UIState] = {}

    def check_and_notify(
        self,
        session_id: str,
        current_state: UIState,
        public_url: str,
    ) -> int:
        """Compare state and send push if transition detected.

        Returns number of notifications sent.
        """
        prev = self._last_state.get(session_id)
        self._last_state[session_id] = current_state

        if current_state not in _NOTIFY_STATES:
            return 0
        if prev == current_state:
            return 0

        subs = self._store.get_subscriptions_for_session(session_id)
        if not subs:
            return 0

        sent = 0
        payload = json.dumps(
            {
                "title": "AgentDeck",
                "body": f"{session_id} needs input",
                "session_id": session_id,
                "url": f"{public_url}/?session={session_id}",
            }
        )
        for sub in subs:
            if self._send_one(sub, payload):
                sent += 1
        return sent

    def _send_one(self, sub: PushSubscription, payload: str) -> bool:
        """Deliver a single push. Returns True on success."""
        info = {
            "endpoint": sub.endpoint,
            "keys": {
                "p256dh": sub.p256dh,
                "auth": sub.auth,
            },
        }
        try:
            webpush(
                subscription_info=info,
                data=payload,
                vapid_private_key=self._private_key,
                vapid_claims=self._claims,
            )
            logger.debug("push_sent", endpoint=sub.endpoint)
            return True
        except WebPushException as e:
            status = getattr(e, "response", None)
            code = getattr(status, "status_code", None)
            if code in (404, 410):
                logger.info(
                    "push_endpoint_gone",
                    endpoint=sub.endpoint,
                )
                self._store.remove_endpoint(sub.endpoint)
            else:
                logger.warning(
                    "push_failed",
                    endpoint=sub.endpoint,
                    error=str(e),
                )
            return False

    def forget_session(self, session_id: str) -> None:
        """Clean up state tracking for a dead session."""
        self._last_state.pop(session_id, None)
