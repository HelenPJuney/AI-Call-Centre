# [ START ]
#     |
#     v
# +--------------------------+
# | dashboard()              |
# | * serve index.html       |
# +--------------------------+
#     |
#     v
# +--------------------------+
# | api_health()             |
# | * combined status check  |
# +--------------------------+
#     |
#     |----> _check_livekit()    * HTTP ping
#     |
#     |----> _check_kafka()      * Producer connect test
#     |
#     |----> _check_gpu_quick()  * pynvml VRAM & Model logic
#     |
#     v
# +--------------------------+
# | api_token()              |
# | * browser auth endpoint  |
# +--------------------------+
#     |
#     |----> _make_livekit_token() * PyJWT encode
#     |
#     v
# +--------------------------+
# | api_create_topics()      |
# | * AIOKafkaAdmin setup    |
# +--------------------------+
#     |
#     v
# +--------------------------+
# | api_pipeline_test()      |
# | * round-trip latency     |
# +--------------------------+
#     |
#     |----> AIOKafkaProducer -> send_and_wait()
#     |
#     |----> AIOKafkaConsumer -> seek() + getone()
#     |
#     v
# +--------------------------+
# | api_queue_status()       |
# | * check consumer lag     |
# +--------------------------+
#     |
#     |----> AIOKafkaConsumer -> end_offsets() - committed()
#     |
#     v
# +--------------------------+
# | api_config()             |
# | * show env settings      |
# +--------------------------+
#     |
#     v
# [ END ]

import asyncio
import json
import logging
import os
import socket
import sys
import time
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ── Add parent dir to path so we can import livekit package ──────────────────
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

# Ensure the app always logs to the console (even when started via uvicorn)
_log_format = "%(asctime)s %(name)s %(levelname)s %(message)s"
_log_handler = logging.StreamHandler(sys.stdout)
_log_handler.setFormatter(logging.Formatter(_log_format))
logger = logging.getLogger("test-server")
if not logger.handlers:
    logger.addHandler(_log_handler)
logger.setLevel(logging.INFO)
logger.info("Entering server.py")

app = FastAPI(title="LiveKit Pipeline Test Dashboard", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# ── Env vars ──────────────────────────────────────────────────────────────────
LIVEKIT_URL    = os.getenv("LIVEKIT_URL",        "ws://localhost:7880")
LIVEKIT_API_KEY    = os.getenv("LIVEKIT_API_KEY",    "devkey")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "devsecret")
KAFKA_BROKERS  = os.getenv("KAFKA_BROKERS",      "localhost:9092").split(",")


# ════════════════════════════════════════════════════════════════════════════════
# HTML dashboard
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    print("[FUNC] Enter: dashboard")
    html_path = Path(__file__).parent / "index.html"
    if html_path.exists():
        res = html_path.read_text(encoding="utf-8")
        print("[FUNC] Exit: dashboard")
        return res
    print("[FUNC] Exit: dashboard")
    return "<h1>index.html not found — place it next to server.py</h1>"


# ════════════════════════════════════════════════════════════════════════════════
# /api/health  — LiveKit + Kafka status
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/api/health")
async def api_health():
    print("[FUNC] Enter: api_health")
    result = {
        "server":        socket.gethostname(),
        "timestamp": time.time(),
        "livekit":   await _check_livekit(),
        "kafka":     await _check_kafka(),
        "gpu":       _check_gpu_quick(),
    }
    print("[FUNC] Exit: api_health")
    return result


async def _check_livekit() -> dict:
    print("[FUNC] Enter: _check_livekit")
    #Try connecting to LiveKit server via HTTP health endpoint.
    try:
        import aiohttp
        url = LIVEKIT_URL.replace("ws://", "http://").replace("wss://", "https://")
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3)) as s:
            try:
                async with s.get(f"{url}/") as r:
                    res = {"status": "ok", "url": LIVEKIT_URL, "http_status": r.status}
                    print("[FUNC] Exit: _check_livekit")
                    return res
            except Exception:
                # LiveKit may not have an HTTP root — try /rtc
                res = {"status": "ok", "url": LIVEKIT_URL,
                        "note": "server reachable (root not HTTP)"}
                print("[FUNC] Exit: _check_livekit")
                return res
    except Exception as e:
        res = {"status": "error", "url": LIVEKIT_URL, "error": str(e)}
        print("[FUNC] Exit: _check_livekit")
        return res


async def _check_kafka() -> dict:
    print("[FUNC] Enter: _check_kafka")
    #Try connecting to Kafka broker.
    try:
        from aiokafka import AIOKafkaProducer
        prod = AIOKafkaProducer(bootstrap_servers=KAFKA_BROKERS)
        await asyncio.wait_for(prod.start(), timeout=5.0)
        await prod.stop()
        res = {"status": "ok", "brokers": KAFKA_BROKERS}
        print("[FUNC] Exit: _check_kafka")
        return res
    except asyncio.TimeoutError:
        res = {"status": "error", "brokers": KAFKA_BROKERS,
                "error": "connection timed out (is Kafka running?)"}
        print("[FUNC] Exit: _check_kafka")
        return res
    except Exception as e:
        res = {"status": "error", "brokers": KAFKA_BROKERS, "error": str(e)}
        print("[FUNC] Exit: _check_kafka")
        return res


def _check_gpu_quick() -> dict:
    print("[FUNC] Enter: _check_gpu_quick")
 
    fallback = int(os.getenv("FALLBACK_MAX_CALLS", "4"))
    try:
        import pynvml
        gpu_index = int(os.getenv("GPU_INDEX", "0"))

        pynvml.nvmlInit()
        handle   = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        mem      = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util     = pynvml.nvmlDeviceGetUtilizationRates(handle)
        name_b   = pynvml.nvmlDeviceGetName(handle)
        gpu_name = name_b.decode() if isinstance(name_b, bytes) else str(name_b)

        total_mb = int(mem.total // (1024 * 1024))
        used_mb  = int(mem.used  // (1024 * 1024))
        free_mb  = int(mem.free  // (1024 * 1024))
        util_pct = int(util.gpu)

        # Adaptive overhead: 20% of VRAM, capped 256–1024 MB
        overhead_mb = int(os.getenv("MODEL_MEMORY_OVERHEAD_MB",
                                    str(min(1024, max(256, total_mb // 5)))))

        # Auto-select best STT model for this GPU (or use env override)
        stt_mb_map = [
            ("whisper_large_v3", 3200, 8000),
            ("whisper_large",    2800, 5000),
            ("whisper_medium",   1500, 3000),
            ("whisper_base",      800, 1500),
            ("whisper_tiny",      600,    0),
        ]
        forced_model = os.getenv("STT_MODEL", "")
        if forced_model:
            stt_model   = forced_model
            stt_vram_mb = {"whisper_tiny": 600, "whisper_base": 800,
                           "whisper_medium": 1500, "whisper_large": 2800,
                           "whisper_large_v3": 3200}.get(forced_model, 1500)
            auto_model = False
        else:
            # Pick the best model whose VRAM cost fits in (free - overhead)
            usable_for_model = free_mb - overhead_mb
            stt_model, stt_vram_mb, auto_model = "whisper_tiny", 600, True
            for name, vram, min_total in stt_mb_map:
                if total_mb >= min_total and usable_for_model >= vram:
                    stt_model, stt_vram_mb = name, vram
                    break

        per_call_mb = stt_vram_mb + 150  # +150 MB for piper TTS

        usable    = max(0, free_mb - overhead_mb)
        max_calls = (usable // per_call_mb) if per_call_mb > 0 else fallback
        if util_pct > 90:
            max_calls = max(0, int(max_calls * 0.7))

        res = {
            "available":     True,
            "gpu_name":      gpu_name,
            "max_calls":     int(max_calls),
            "vram_total_mb": total_mb,
            "vram_used_mb":  used_mb,
            "vram_free_mb":  free_mb,
            "gpu_util_pct":  util_pct,
            "per_call_mb":   per_call_mb,
            "stt_model":     stt_model,
            "stt_auto":      auto_model,
            "overhead_mb":   overhead_mb,
        }
        print("[FUNC] Exit: _check_gpu_quick")
        return res
    except ImportError:
        res = {"available": False, "error": "pynvml not installed",
                "max_calls": fallback, "fallback_max_calls": fallback}
        print("[FUNC] Exit: _check_gpu_quick")
        return res
    except Exception as e:
        res = {"available": False, "error": str(e),
                "max_calls": fallback, "fallback_max_calls": fallback}
        print("[FUNC] Exit: _check_gpu_quick")
        return res


# ════════════════════════════════════════════════════════════════════════════════
# /api/token  — generate a LiveKit JWT for browser
# ════════════════════════════════════════════════════════════════════════════════

def _make_livekit_token(api_key: str, api_secret: str,
                        room_id: str, identity: str, name: str = "Test Caller") -> str:
    print("[FUNC] Enter: _make_livekit_token")
  
    import jwt as pyjwt  # PyJWT
    now = int(time.time())
    payload = {
        "iss":  api_key,
        "sub":  identity,
        "iat":  now,
        "exp":  now + 3600,
        "name": name,
        "video": {
            "roomJoin":    True,
            "room":         room_id,
            "canPublish":   True,
            "canSubscribe": True,
        },
    }
    res = pyjwt.encode(payload, api_secret, algorithm="HS256")
    print("[FUNC] Exit: _make_livekit_token")
    return res


@app.get("/api/token")
async def api_token(lang: str = "en", llm: str = "gemini", voice: str = ""):
    print("[FUNC] Enter: api_token")
    """Generate a LiveKit browser token (standalone — no backend.core needed)."""
    import uuid
    try:
        room_id    = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        identity   = f"user-{session_id[:8]}"
        token = _make_livekit_token(
            LIVEKIT_API_KEY, LIVEKIT_API_SECRET, room_id, identity
        )
    except ImportError:
        print("[FUNC] Exit: api_token")
        return JSONResponse(
            {"error": "PyJWT not installed — run: pip install PyJWT"},
            status_code=500,
        )
    except Exception as e:
        print("[FUNC] Exit: api_token")
        return JSONResponse({"error": str(e)}, status_code=500)

    res = {
        "token":      token,
        "url":        LIVEKIT_URL,
        "room":       room_id,
        "session_id": session_id,
        "identity":   identity,
        "lang":       lang,
        "llm":        llm,
        "voice":      voice,
    }
    print("[FUNC] Exit: api_token")
    return res


# ════════════════════════════════════════════════════════════════════════════════
# /api/gpu  — detailed GPU stats
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/api/gpu")
async def api_gpu():
    print("[FUNC] Enter: api_gpu")
    res = _check_gpu_quick()
    print("[FUNC] Exit: api_gpu")
    return res


# ════════════════════════════════════════════════════════════════════════════════
# /api/kafka  — Kafka topic metadata
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/api/kafka")
async def api_kafka():
    print("[FUNC] Enter: api_kafka")
    topics_to_check = [
        "call_requests", "call_assignments", "gpu_capacity",
        "call_started", "call_completed", "call_failed",
        "worker_heartbeat", "call_dlq",
    ]
    try:
        from aiokafka import AIOKafkaConsumer
        from aiokafka.admin import AIOKafkaAdminClient

        admin = AIOKafkaAdminClient(
            bootstrap_servers=KAFKA_BROKERS,
            request_timeout_ms=5000,
        )
        await asyncio.wait_for(admin.start(), timeout=5.0)
        try:
            existing = await admin.list_topics()
            topic_status = {}
            for t in topics_to_check:
                topic_status[t] = "exists" if t in existing else "missing"
        finally:
            await admin.close()

        res = {
            "status":  "ok",
            "brokers": KAFKA_BROKERS,
            "topics":  topic_status,
        }
        print("[FUNC] Exit: api_kafka")
        return res
    except Exception as e:
        res = {
            "status":  "error",
            "brokers": KAFKA_BROKERS,
            "error":   str(e),
            "topics":  {t: "unknown" for t in topics_to_check},
        }
        print("[FUNC] Exit: api_kafka")
        return res


# ════════════════════════════════════════════════════════════════════════════════
# /api/kafka/create-topics  — create all required topics if missing
# ════════════════════════════════════════════════════════════════════════════════

_REQUIRED_TOPICS = {
    "call_requests":     {"num_partitions": 4, "replication_factor": 1},
    "call_assignments": {"num_partitions": 4, "replication_factor": 1},
    "gpu_capacity":      {"num_partitions": 1, "replication_factor": 1},
    "call_started":      {"num_partitions": 1, "replication_factor": 1},
    "call_completed":    {"num_partitions": 1, "replication_factor": 1},
    "call_failed":       {"num_partitions": 1, "replication_factor": 1},
    "worker_heartbeat": {"num_partitions": 1, "replication_factor": 1},
    "call_dlq":          {"num_partitions": 1, "replication_factor": 1},
}

@app.post("/api/kafka/create-topics")
async def api_create_topics():
    print("[FUNC] Enter: api_create_topics")
    """Create all required Kafka topics that are currently missing."""
    try:
        from aiokafka.admin import AIOKafkaAdminClient, NewTopic

        admin = AIOKafkaAdminClient(
            bootstrap_servers=KAFKA_BROKERS,
            request_timeout_ms=10000,
        )
        await asyncio.wait_for(admin.start(), timeout=8.0)
        results = {}
        try:
            existing = await admin.list_topics()
            to_create = [
                NewTopic(name=t, **cfg)
                for t, cfg in _REQUIRED_TOPICS.items()
                if t not in existing
            ]
            if to_create:
                resp = await admin.create_topics(to_create, validate_only=False)
                for t in _REQUIRED_TOPICS:
                    if t in existing:
                        results[t] = "already_exists"
                    else:
                        results[t] = "created"
            else:
                results = {t: "already_exists" for t in _REQUIRED_TOPICS}
        finally:
            await admin.close()

        res = {"status": "ok", "topics": results, "brokers": KAFKA_BROKERS}
        print("[FUNC] Exit: api_create_topics")
        return res
    except Exception as e:
        res = {"status": "error", "error": str(e)}
        print("[FUNC] Exit: api_create_topics")
        return res


# ════════════════════════════════════════════════════════════════════════════════
# /api/pipeline-test  — produce a test message and verify receipt
# ════════════════════════════════════════════════════════════════════════════════

@app.post("/api/pipeline-test")
async def api_pipeline_test():
    print("[FUNC] Enter: api_pipeline_test")

    import uuid
    results = {"steps": [], "success": False, "latency_ms": None}
    t_start = time.time()

    try:
        from aiokafka import AIOKafkaProducer, AIOKafkaConsumer, TopicPartition

        # Step 1: produce
        test_payload = json.dumps({
            "schema_version": 1,
            "session_id": str(uuid.uuid4()),
            "room_id":     str(uuid.uuid4()),
            "lang": "en", "llm": "gemini", "voice": "",
            "model_path": "", "agent_name": "test",
            "timestamp": time.time(), "priority": 0, "retry_count": 0,
            "assigned_node": None,
            "_test": True,
        }).encode()

        prod = AIOKafkaProducer(bootstrap_servers=KAFKA_BROKERS)
        await asyncio.wait_for(prod.start(), timeout=5.0)
        meta = await asyncio.wait_for(
            prod.send_and_wait("call_requests", value=test_payload,
                               key=b"pipeline-test"),
            timeout=5.0,
        )
        await prod.stop()
        results["steps"].append({
            "step": "produce", "status": "ok",
            "partition": meta.partition, "offset": meta.offset,
        })

        # Step 2: consume (use unique group so we get this exact message)
        group_id = f"pipeline-test-{uuid.uuid4().hex[:8]}"
        con = AIOKafkaConsumer(
            bootstrap_servers=KAFKA_BROKERS,
            group_id=group_id,
            auto_offset_reset="latest",
            enable_auto_commit=True,
            consumer_timeout_ms=3000,
        )
        tp = TopicPartition("call_requests", meta.partition)
        await asyncio.wait_for(con.start(), timeout=5.0)
        con.assign([tp])
        con.seek(tp, meta.offset)  # seek() is synchronous — do NOT await

        received = None
        try:
            msg = await asyncio.wait_for(con.getone(), timeout=5.0)
            received = json.loads(msg.value)
        except asyncio.TimeoutError:
            results["steps"].append({"step": "consume", "status": "timeout"})
        finally:
            await con.stop()

        if received and received.get("_test"):
            results["steps"].append({"step": "consume", "status": "ok",
                                     "session_id": received.get("session_id", "")[:8]})
            results["success"] = True
            results["latency_ms"] = round((time.time() - t_start) * 1000, 1)
        else:
            results["steps"].append({"step": "consume", "status": "wrong_message"})

    except Exception as e:
        results["steps"].append({"step": "error", "status": "error", "error": str(e)})

    print("[FUNC] Exit: api_pipeline_test")
    return results


# ════════════════════════════════════════════════════════════════════════════════
# /api/queue-status  — call_requests consumer lag
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/api/queue-status")
async def api_queue_status():
    print("[FUNC] Enter: api_queue_status")
    try:
        from aiokafka import AIOKafkaConsumer, TopicPartition
        con = AIOKafkaConsumer(
            "call_requests",
            bootstrap_servers=KAFKA_BROKERS,
            group_id="scheduler-group",
            enable_auto_commit=False,
            auto_offset_reset="latest",
        )
        await asyncio.wait_for(con.start(), timeout=5.0)
        try:
            assignment = con.assignment()
            if not assignment:
                # force metadata fetch
                await asyncio.sleep(0.5)
                assignment = con.assignment()
            end_offsets = await con.end_offsets(list(assignment))
            lag = 0
            for tp, end_off in end_offsets.items():
                try:
                    committed = await con.committed(tp)
                    pos = committed or 0
                    lag += max(0, end_off - pos)
                except Exception:
                    pass
        finally:
            await con.stop()
        res = {"status": "ok", "queue_depth": lag, "unit": "messages"}
        print("[FUNC] Exit: api_queue_status")
        return res
    except Exception as e:
        res = {"status": "error", "error": str(e), "queue_depth": None}
        print("[FUNC] Exit: api_queue_status")
        return res


# ════════════════════════════════════════════════════════════════════════════════
# /api/config  — show current configuration (no secrets)
# ════════════════════════════════════════════════════════════════════════════════

@app.get("/api/config")
async def api_config():
    print("[FUNC] Enter: api_config")
    res = {
        "livekit_url":   LIVEKIT_URL,
        "kafka_brokers": KAFKA_BROKERS,
        "node_id":       socket.gethostname(),
        "stt_model":     os.getenv("STT_MODEL", "whisper_medium"),
        "llm_key":       os.getenv("LLM_KEY", "gemini"),
        "gpu_index":     int(os.getenv("GPU_INDEX", "0")),
        "fallback_max_calls": int(os.getenv("FALLBACK_MAX_CALLS", "4")),
    }
    print("[FUNC] Exit: api_config")
    return res


# ════════════════════════════════════════════════════════════════════════════════
# Entry point
# ════════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("  LiveKit Pipeline Test Dashboard")
    print("  http://localhost:8888")
    print("=" * 60)
    logger.info("%s", "=" * 60)
    logger.info("  LiveKit Pipeline Test Dashboard")
    logger.info("  http://localhost:8888")
    logger.info("%s", "=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8888, reload=False, log_level="info")