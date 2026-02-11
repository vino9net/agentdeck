"""VAPID key management for Web Push."""

import base64
import json
from pathlib import Path

from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
)
from py_vapid import Vapid02


def _public_key_b64url(vapid: Vapid02) -> str:
    """Extract application server key as URL-safe base64."""
    raw = vapid.public_key.public_bytes(
        encoding=Encoding.X962,
        format=PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def load_or_create_vapid_keys(
    state_dir: str | Path,
) -> tuple[str, Path]:
    """Load or auto-generate VAPID EC key pair.

    Args:
        state_dir: Directory for persistent state files.

    Returns:
        (application_server_key, private_key_pem_path)
    """
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    pem_path = state_dir / "vapid_private.pem"
    json_path = state_dir / "vapid_keys.json"

    if pem_path.exists() and json_path.exists():
        keys = json.loads(json_path.read_text())
        return keys["public_key"], pem_path

    vapid = Vapid02()
    vapid.generate_keys()
    vapid.save_key(str(pem_path))

    public_key = _public_key_b64url(vapid)
    json_path.write_text(json.dumps({"public_key": public_key}))
    return public_key, pem_path
