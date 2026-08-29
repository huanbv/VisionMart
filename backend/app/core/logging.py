"""Centralised structured logging configuration."""

from __future__ import annotations

import logging
import sys
from logging.config import dictConfig

from app.config.settings import get_settings


def configure_logging() -> None:
    settings = get_settings()

    formatter: dict[str, object]
    if settings.LOG_FORMAT == "json":
        formatter = {
            "()": "pythonjsonlogger.jsonlogger.JsonFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s %(message)s",
        }
    else:
        formatter = {
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        }

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": formatter},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                    "formatter": "default",
                }
            },
            "root": {"level": settings.LOG_LEVEL, "handlers": ["console"]},
            "loggers": {
                "uvicorn":        {"handlers": ["console"], "level": settings.LOG_LEVEL, "propagate": False},
                "uvicorn.error":  {"handlers": ["console"], "level": settings.LOG_LEVEL, "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
                "sqlalchemy.engine": {"handlers": ["console"], "level": "WARNING", "propagate": False},
            },
        }
    )

    logging.getLogger(__name__).debug("Logging configured (level=%s)", settings.LOG_LEVEL)
