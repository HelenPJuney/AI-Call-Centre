"""
backend/livekit/kafka/lifespan.py
──────────────────────────────────────────────────────────────────────────────
FastAPI lifespan context manager that starts and stops the Kafka producer
singleton cleanly.

Usage in your app.py:

    from contextlib import asynccontextmanager
    from fastapi import FastAPI
    from backend.livekit.kafka.lifespan import kafka_lifespan

    # Option A — dedicated lifespan (new projects):
    app = FastAPI(lifespan=kafka_lifespan)

    # Option B — combine with an existing lifespan:
    @asynccontextmanager
    async def app_lifespan(app: FastAPI):
        async with kafka_lifespan(app):
            yield

    app = FastAPI(lifespan=app_lifespan)

    # Option C — legacy startup/shutdown events (older FastAPI):
    from backend.livekit.kafka.lifespan import start_kafka_producer, stop_kafka_producer
    app.add_event_handler("startup",  start_kafka_producer)
    app.add_event_handler("shutdown", stop_kafka_producer)
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

logger = logging.getLogger("callcenter.kafka.lifespan")


# ── Standalone startup / shutdown coroutines (for legacy event handlers) ──────

async def start_kafka_producer() -> None:
    """
    Start the Kafka producer singleton.
    Attach to FastAPI startup event or call from your lifespan context.
    """
    from .producer import get_producer
    producer = get_producer()
    await producer.start()
    logger.info("[Lifespan] Kafka producer started  active=%s", producer.is_kafka_active)


async def stop_kafka_producer() -> None:
    """
    Flush and close the Kafka producer singleton.
    Attach to FastAPI shutdown event or call from your lifespan context.
    """
    from .producer import get_producer
    producer = get_producer()
    await producer.stop()
    logger.info("[Lifespan] Kafka producer stopped")


# ── asynccontextmanager lifespan (FastAPI 0.93+) ──────────────────────────────

@asynccontextmanager
async def kafka_lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.

    Use as:
        app = FastAPI(lifespan=kafka_lifespan)
    """
    await start_kafka_producer()
    try:
        yield
    finally:
        await stop_kafka_producer()
