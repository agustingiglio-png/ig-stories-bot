"""Timezone Argentina: la logica no depende del reloj del servidor."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from igstories.config import TZ, next_publish_dt, now_ar


def test_tz_is_argentina():
    assert str(TZ) == "America/Argentina/Buenos_Aires"


def test_argentina_is_utc_minus_3():
    # Argentina no tiene horario de verano: offset fijo -3.
    sample = datetime(2026, 1, 15, 12, 0, tzinfo=TZ)
    assert sample.utcoffset().total_seconds() == -3 * 3600
    sample2 = datetime(2026, 7, 15, 12, 0, tzinfo=TZ)
    assert sample2.utcoffset().total_seconds() == -3 * 3600


def test_now_ar_has_tz():
    assert now_ar().tzinfo is not None


def test_next_publish_is_13h():
    # a las 10:00 ART, la proxima publicacion es hoy 13:00
    ref = datetime(2026, 8, 19, 10, 0, tzinfo=TZ)
    nxt = next_publish_dt(ref)
    assert (nxt.hour, nxt.minute) == (13, 0)
    assert nxt.date() == ref.date()


def test_next_publish_rolls_to_tomorrow():
    # a las 14:00 ART (ya paso), la proxima es mañana 13:00
    ref = datetime(2026, 8, 19, 14, 0, tzinfo=TZ)
    nxt = next_publish_dt(ref)
    assert (nxt.hour, nxt.minute) == (13, 0)
    assert nxt.day == 20


def test_cron_utc_equivalent():
    # 13:00 ART == 16:00 UTC (lo que usa el cron del workflow)
    ar = datetime(2026, 8, 19, 13, 0, tzinfo=TZ)
    utc = ar.astimezone(ZoneInfo("UTC"))
    assert utc.hour == 16
