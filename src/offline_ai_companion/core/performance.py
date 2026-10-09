"""Low-overhead stage timings that never log arguments or model output."""

import logging
from functools import wraps
from time import perf_counter
from offline_ai_companion.core.runtime_metrics import metrics, TIMINGS

logger = logging.getLogger("nova.performance")


def timed(stage: str):
    """Log duration on success, error or interruption; preserve the callable."""
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            started = perf_counter()
            status = "error"
            try:
                result = function(*args, **kwargs)
                status = "ok"
                return result
            finally:
                duration = perf_counter() - started
                if stage in TIMINGS:
                    metrics.observe(stage, duration, status)
                logger.info(
                    "stage=%s duration_ms=%.3f status=%s",
                    stage, duration * 1000, status,
                )
        return measured
    return decorate


def enable_performance_logging() -> None:
    """Enable numeric stage logs on stderr without changing other loggers."""
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[PERF] %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
