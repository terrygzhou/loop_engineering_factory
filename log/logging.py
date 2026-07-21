"""Structured JSON logging — writes to stdout for Docker."""
import json
import logging
import sys

def setup_logger(name: str = "loop_factory") -> logging.Logger:
    """Configure JSON logger. Idempotent — safe to call multiple times."""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    from config.loader import config
    logger.setLevel(getattr(logging, config.observability.log_level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '{"ts":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
    ))
    logger.addHandler(handler)

    logger.propagate = False
    return logger

def log_event(logger: logging.Logger, event: str, **ctx):
    """Structured event logging — all context as JSON fields."""
    fields = {"event": event, **ctx}
    logger.info(json.dumps(fields))
