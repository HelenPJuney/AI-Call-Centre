"""
backend/livekit
──────────────────────────────────────────────────────────────────────────────
LiveKit-based communication layer — replaces the old aiortc WebRTC layer.
Now includes Kafka-based call scheduling and GPU-aware scaling.

Integration in backend/app.py:

    # Minimal (no Kafka):
    from backend.livekit import livekit_router
    app.include_router(livekit_router)

    # Full (with Kafka producer lifecycle):
    from backend.livekit import livekit_router, kafka_health_router
    from backend.livekit.kafka.lifespan import kafka_lifespan
    app = FastAPI(lifespan=kafka_lifespan)
    app.include_router(livekit_router)
    app.include_router(kafka_health_router)   # /livekit/kafka/health + /metrics

Endpoints:
    GET  /livekit/token              — issue JWT + submit to Kafka Scheduler
    GET  /livekit/health             — LiveKit + Kafka connectivity status
    GET  /livekit/queue-status/{id}  — poll queue position for a session
    GET  /livekit/kafka/health       — Kafka integration liveness check
    GET  /livekit/kafka/metrics      — Prometheus metrics

Call flow (Kafka path):
    Browser → GET /livekit/token
    Backend → produce call_request → Kafka → Call Scheduler
    Scheduler → GPU-aware assignment → Worker Service on GPU Node
    Worker Service → spawn ai_worker_task → LiveKit room.connect
    Worker  → VAD → STT → LLM → TTS → publish audio track
    Browser ← DataChannel: queue_update | call_start | greeting | transcript …

Call flow (fallback — no Kafka):
    Identical to original: ai_worker_task spawned directly by FastAPI.

Control channel (LiveKit DataChannel):
    Browser → Worker : { type: "interrupt" } | { type: "hangup" }
    Worker  → Browser: { type: "greeting" }  | { type: "transcript" }
                     | { type: "response" }  | { type: "barge_in" }
                     | { type: "error" }     | { type: "hangup" }
                     | { type: "queue_update", "position": N, "eta_sec": N }
                     | { type: "call_start" }
"""

from .ai_worker import livekit_router
from .kafka.health import kafka_health_router

__all__ = ["livekit_router", "kafka_health_router"]
