"""Logging con timestamps en hora Argentina y filtro anti-secretos.

Regla de oro: jamas imprimir un token/secret completo en los logs.
El SecretFilter censura cualquier valor sensible conocido si se cuela en un mensaje.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from .config import LOGS_DIR, TZ

_SECRETS: set[str] = set()


def register_secret(value: str) -> None:
    """Registra un valor que NUNCA debe aparecer entero en los logs."""
    if value and len(value) >= 6:
        _SECRETS.add(value)


class SecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        for secret in _SECRETS:
            if secret in msg:
                record.msg = msg.replace(secret, "***REDACTED***")
                record.args = ()
        return True


class _ARFormatter(logging.Formatter):
    """Formatea la hora en America/Argentina/Buenos_Aires."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, TZ)
        return dt.strftime(datefmt or "%Y-%m-%d %H:%M:%S")


def setup_logging(run_date: str | None = None, verbose: bool = True) -> logging.Logger:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("igstories")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    fmt = _ARFormatter("%(asctime)s - %(levelname)s - %(message)s")
    secret_filter = SecretFilter()

    console = logging.StreamHandler()
    console.setLevel(logging.INFO if verbose else logging.WARNING)
    console.setFormatter(fmt)
    console.addFilter(secret_filter)
    logger.addHandler(console)

    logfile = LOGS_DIR / (f"{run_date}.log" if run_date else "app.log")
    fileh = logging.FileHandler(logfile, encoding="utf-8")
    fileh.setLevel(logging.DEBUG)
    fileh.setFormatter(fmt)
    fileh.addFilter(secret_filter)
    logger.addHandler(fileh)

    logger.propagate = False
    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("igstories")
