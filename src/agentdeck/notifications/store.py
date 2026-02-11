"""JSON-file-backed push subscription store."""

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PushSubscription:
    """A single Web Push subscription."""

    endpoint: str
    p256dh: str
    auth: str
    session_id: str


class PushSubscriptionStore:
    """Minimal push subscription store backed by a JSON file.

    Designed for single-user usage with a handful of
    subscriptions. Thread-safe is not needed since all
    access runs on the async event loop.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._subs: list[PushSubscription] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._subs = []
            return
        try:
            data = json.loads(self._path.read_text())
            self._subs = [PushSubscription(**s) for s in data]
        except (json.JSONDecodeError, OSError, TypeError):
            self._subs = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps([asdict(s) for s in self._subs], indent=2))

    def subscribe(
        self,
        endpoint: str,
        p256dh: str,
        auth: str,
        session_id: str,
    ) -> None:
        """Add or upsert a subscription."""
        # Remove existing match (upsert)
        self._subs = [
            s
            for s in self._subs
            if not (s.endpoint == endpoint and s.session_id == session_id)
        ]
        self._subs.append(
            PushSubscription(
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                session_id=session_id,
            )
        )
        self._save()

    def unsubscribe(self, endpoint: str, session_id: str) -> None:
        """Remove a subscription for a specific session."""
        before = len(self._subs)
        self._subs = [
            s
            for s in self._subs
            if not (s.endpoint == endpoint and s.session_id == session_id)
        ]
        if len(self._subs) != before:
            self._save()

    def get_subscriptions_for_session(self, session_id: str) -> list[PushSubscription]:
        """All subscriptions targeting a session."""
        return [s for s in self._subs if s.session_id == session_id]

    def get_session_ids_for_endpoint(self, endpoint: str) -> list[str]:
        """Session IDs subscribed from a given endpoint."""
        return [s.session_id for s in self._subs if s.endpoint == endpoint]

    def remove_endpoint(self, endpoint: str) -> None:
        """Remove all subscriptions for an endpoint (410 cleanup)."""
        before = len(self._subs)
        self._subs = [s for s in self._subs if s.endpoint != endpoint]
        if len(self._subs) != before:
            self._save()
