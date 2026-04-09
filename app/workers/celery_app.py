"""
VSM Backend – Celery Application Factory (PRD 2 §5)

Configures Celery with Redis broker + result backend.
Supports both local Redis (redis://) and Upstash (rediss://).
All workers import `celery_app` from this module.
"""

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "vsm_backend",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "app.workers.event_processor",
        "app.workers.nlp_worker",
        "app.workers.aggregation_worker",
        "app.workers.ai_trigger_worker",
        "app.tasks.apply_decision_task",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,

    # ── Retry Configuration ───────────────────────────────────────────────────
    task_max_retries=settings.celery_task_max_retries,
    task_acks_late=True,             # Ensure message not lost if worker dies
    task_reject_on_worker_lost=True,

    # ── Routing: Each worker type binds to its own queue ─────────────────────
    task_routes={
        "app.workers.event_processor.*": {"queue": "event_processing"},
        "app.workers.nlp_worker.*": {"queue": "nlp_processing"},
        "app.workers.aggregation_worker.*": {"queue": "aggregation"},
        "app.workers.ai_trigger_worker.*": {"queue": "ai_trigger"},
        "app.tasks.apply_decision_task.*": {"queue": "ai_trigger"},
    },

    # ── Beat Schedule (periodic tasks) ───────────────────────────────────────
    beat_schedule={
        "close-expired-aggregation-windows": {
            "task": "app.workers.aggregation_worker.close_expired_windows",
            "schedule": settings.aggregation_window_seconds,
        },
        "retry-failed-queue-events": {
            "task": "app.workers.event_processor.retry_failed_events",
            "schedule": 60.0,   # every minute
        },
    },
)

# ── Upstash / TLS Support ─────────────────────────────────────────────────────
# Auto-detects rediss:// scheme and applies SSL config.
# Works for: Upstash, Redis Cloud, ElastiCache, any TLS Redis.
if settings.celery_broker_url.startswith("rediss://"):
    import ssl

    _ssl_config = {"ssl_cert_reqs": ssl.CERT_NONE}

    celery_app.conf.update(
        broker_use_ssl=_ssl_config,
        redis_backend_use_ssl=_ssl_config,
        broker_transport_options={
            "visibility_timeout": 3600,   # 1 hour
            "socket_timeout": 10,
            "socket_connect_timeout": 10,
        },
    )
