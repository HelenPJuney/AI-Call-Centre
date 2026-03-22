"""
backend/livekit/token_service.py
──────────────────────────────────────────────────────────────────────────────
JWT token generation for LiveKit room access.

Requires:
    pip install livekit-api

Environment variables (set in .env or export before starting):
    LIVEKIT_URL        — ws://localhost:7880  (or wss:// in production)
    LIVEKIT_API_KEY    — devkey
    LIVEKIT_API_SECRET — devsecret

Token grants:
    room_join    — allow participant to enter the room
    can_publish  — allow publishing audio tracks
    can_subscribe — allow subscribing to other participants' tracks

Usage:
    token = generate_token("room-uuid", "user-abc123", name="User")
    worker_token = generate_token(
        "room-uuid", "ai-worker-abc", name="AI Agent",
        can_publish=True, can_subscribe=True,
    )
"""

import os

# ── LiveKit server coordinates (read from env, fallback to local dev values) ─
LIVEKIT_URL        = os.getenv("LIVEKIT_URL",        "ws://localhost:7880")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY",    "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "devsecret")


# --------------------------------------------------
# generate_token -> Build a signed JWT for one LiveKit room participant
#    ||
# livekit-api AccessToken -> VideoGrants -> to_jwt()
#    ||
# Returns signed JWT string for browser SDK or Python SDK room.connect()
# --------------------------------------------------
def generate_token(
    room_name:     str,
    identity:      str,
    name:          str  = "",
    *,
    can_publish:   bool = True,
    can_subscribe: bool = True,
) -> str:
    """
    Generate a signed LiveKit JWT for the given participant identity.

    Args:
        room_name     — LiveKit room identifier (UUID string)
        identity      — Unique participant ID (e.g. "user-abc", "ai-worker-abc")
        name          — Display name shown in room (optional)
        can_publish   — Allow the participant to publish audio/video tracks
        can_subscribe — Allow the participant to receive other participants' tracks

    Returns:
        Signed JWT string ready for use with:
          • livekit-client JS:  room.connect(url, token)
          • livekit Python SDK: await room.connect(url, token)
    """
    from livekit.api import AccessToken, VideoGrants

    grants = VideoGrants(
        room_join    = True,
        room         = room_name,
        can_publish  = can_publish,
        can_subscribe= can_subscribe,
    )

    token = (
        AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(identity)
        .with_name(name or identity)
        .with_grants(grants)
        .to_jwt()
    )
    return token
