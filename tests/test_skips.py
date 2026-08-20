"""Skips: hoy, fecha futura, unskip, y efecto sobre publish."""
from __future__ import annotations

from igstories import db, publisher
from igstories.config import today_ar


def test_skip_today(tmp_env):
    day = today_ar().isoformat()
    db.add_skip(day)
    assert db.is_skipped(day) is True


def test_skip_future_date(tmp_env):
    db.add_skip("2099-01-01")
    assert db.is_skipped("2099-01-01") is True
    assert db.is_skipped("2099-01-02") is False


def test_unskip(tmp_env):
    day = today_ar().isoformat()
    db.add_skip(day)
    assert db.remove_skip(day) is True
    assert db.is_skipped(day) is False
    # unskip de algo que no estaba: devuelve False sin romper
    assert db.remove_skip(day) is False


def test_skip_blocks_publish(photos10, dummy_hosting, fake_settings, monkeypatch):
    from tests.conftest import FakeClient
    day = today_ar().isoformat()
    db.add_skip(day)
    monkeypatch.setattr(publisher, "_client", lambda s: FakeClient())
    res = publisher.publish(fake_settings)
    assert res.status == "SKIPPED"
    assert res.skipped is True
    assert db.get_run(day)["status"] == "SKIPPED"
