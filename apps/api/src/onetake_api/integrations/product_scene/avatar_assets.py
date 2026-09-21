from __future__ import annotations

from pathlib import Path

AVATAR_DIR = Path(__file__).resolve().parents[2] / "assets" / "avatar"
MOCK_AVATAR_PATH = AVATAR_DIR / "high-res-avatar-9x16.png"


def load_mock_avatar() -> bytes:
    if not MOCK_AVATAR_PATH.is_file():
        raise FileNotFoundError(f"mock avatar asset missing: {MOCK_AVATAR_PATH}")
    return MOCK_AVATAR_PATH.read_bytes()