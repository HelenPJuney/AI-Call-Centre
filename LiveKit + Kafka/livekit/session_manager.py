"""
backend/livekit/session_manager.py
──────────────────────────────────────────────────────────────────────────────
Thread-safe registry of all active LiveKit AI worker sessions.

Replaces the old backend/webrtc/session_manager.py.

Instead of closing RTCPeerConnection, cleanup_session:
  • Signals the worker to stop via session.closed = True
  • Stops the TtsAudioSource pump
  • Removes the session from the registry

The LiveKit room.disconnect() is called inside the worker task's finally
block — not here — to keep lifecycle control in one place.

A single module-level instance `livekit_session_manager` is shared across
all worker tasks and the token endpoint.
"""

# ==========================================================
# EXECUTION FLOW
# ==========================================================
#
# +-------------------------------+
# | add()                         |
# | * register new session        |
# +-------------------------------+
#     |
#     v
# +-------------------------------+
# | get()                         |
# | * lookup by session_id        |
# +-------------------------------+
#     |
#     v
# +-------------------------------+
# | cleanup_session()             |
# | * stop pump, mark closed      |
# +-------------------------------+
#     |
#     |----> stop()
#     |----> remove()
#     |
#     v
# +-------------------------------+
# | cleanup_all()                 |
# | * shutdown all sessions       |
# +-------------------------------+
#     |
#     v
# [ END ]
# ==========================================================

import asyncio
import logging
from typing import Dict, Optional

from .livekit_session import LiveKitSession

logger = logging.getLogger("callcenter.livekit.sessions")


# --------------------------------------------------
# LiveKitSessionManager -> Registry for active LiveKit AI worker sessions
#    ||
# add / remove / get -> Registry operations (asyncio.Lock-protected)
#    ||
# cleanup_session -> close audio source + mark closed + remove
# --------------------------------------------------
class LiveKitSessionManager:
    """
    Async-safe registry for LiveKit AI worker sessions.

    Usage inside a worker task:
        session = LiveKitSession(...)
        await livekit_session_manager.add(session)
        try:
            ...
        finally:
            await livekit_session_manager.cleanup_session(session.session_id)
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, LiveKitSession] = {}
        self._lock = asyncio.Lock()

    # ── Registry operations ───────────────────────────────────────────────────

    async def add(self, session: LiveKitSession) -> None:
        """Register a newly created session."""
        async with self._lock:
            self._sessions[session.session_id] = session
        logger.info(
            "[Sessions] + added   session=%s  total=%d",
            session.session_id[:8], len(self._sessions),
        )

    async def remove(self, session_id: str) -> Optional[LiveKitSession]:
        """Remove and return session from registry (does NOT close resources)."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)
        if session:
            logger.info(
                "[Sessions] - removed session=%s  total=%d",
                session_id[:8], len(self._sessions),
            )
        return session

    def get(self, session_id: str) -> Optional[LiveKitSession]:
        """Synchronous lookup — returns session or None."""
        return self._sessions.get(session_id)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def cleanup_session(self, session_id: str) -> None:
        """
        Stop the session's audio source pump, mark closed, and remove from
        registry.  Safe to call multiple times — guarded by session.closed.
        """
        session = await self.remove(session_id)
        if session is None:
            return   # already removed

        if session.closed:
            return   # already being cleaned up

        session.closed = True

        # Stop the TTS audio pump if it was started
        if session.audio_source is not None:
            try:
                session.audio_source.stop()
            except Exception:
                pass

        logger.info("[Sessions] cleanup done  session=%s", session_id[:8])

    async def cleanup_all(self) -> None:
        """Signal all sessions to close. Called from server shutdown."""
        async with self._lock:
            ids = list(self._sessions.keys())
        for sid in ids:
            await self.cleanup_session(sid)
        logger.info("[Sessions] all sessions cleaned up")

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def count(self) -> int:
        return len(self._sessions)

    @property
    def session_ids(self) -> list:
        return list(self._sessions.keys())


# ── Module singleton ──────────────────────────────────────────────────────────
livekit_session_manager = LiveKitSessionManager()
