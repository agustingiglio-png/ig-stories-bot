"""Idempotencia, doble ejecucion, publicacion parcial y reanudacion."""
from __future__ import annotations

import pytest

from igstories import db, publisher
from igstories.config import today_ar
from igstories.instagram import (AuthError, ImageRejectedError, RateLimitError,
                                 TransientError)
from tests.conftest import FakeClient, url_for


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(publisher.time, "sleep", lambda *_: None)


def test_full_publish(photos10, dummy_hosting, fake_settings, monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(publisher, "_client", lambda s: client)
    res = publisher.publish(fake_settings)
    assert res.status == "COMPLETED"
    assert res.published == 10
    assert len(client.published) == 10


def test_double_run_does_not_republish(photos10, dummy_hosting, fake_settings, monkeypatch):
    client1 = FakeClient()
    monkeypatch.setattr(publisher, "_client", lambda s: client1)
    publisher.publish(fake_settings)

    # segunda corrida: no debe volver a publicar nada
    client2 = FakeClient()
    monkeypatch.setattr(publisher, "_client", lambda s: client2)
    res = publisher.publish(fake_settings)
    assert res.status == "COMPLETED"
    assert len(client2.published) == 0


def test_partial_then_resume(photos10, dummy_hosting, fake_settings, monkeypatch):
    day = today_ar().isoformat()
    # seq 4 falla permanentemente la primera corrida
    behavior = {url_for(4): [TransientError("temporal"), TransientError("temporal"),
                             TransientError("temporal"), TransientError("temporal")]}
    client1 = FakeClient(behavior=behavior)
    monkeypatch.setattr(publisher, "_client", lambda s: client1)
    res = publisher.publish(fake_settings)
    assert res.status == "FAILED"

    rows = {r["seq"]: r["status"] for r in db.get_stories(day)}
    assert rows[4] == "FAILED"
    published_first = sum(1 for v in rows.values() if v == "PUBLISHED")
    assert published_first == 9  # todas menos la 4

    # reanudar: ahora seq 4 anda. Solo debe publicar la que falta.
    client2 = FakeClient()  # sin fallas
    monkeypatch.setattr(publisher, "_client", lambda s: client2)
    res2 = publisher.publish(fake_settings)
    assert res2.status == "COMPLETED"
    assert len(client2.published) == 1  # solo la seq 4
    rows2 = {r["seq"]: r["status"] for r in db.get_stories(day)}
    assert all(v == "PUBLISHED" for v in rows2.values())


def test_rate_limit_retries_then_succeeds(photos10, dummy_hosting, fake_settings, monkeypatch):
    behavior = {url_for(2): [RateLimitError("429"), RateLimitError("429")]}  # 2 fallos, 3er ok
    client = FakeClient(behavior=behavior)
    monkeypatch.setattr(publisher, "_client", lambda s: client)
    res = publisher.publish(fake_settings)
    assert res.status == "COMPLETED"
    assert res.published == 10


def test_transient_retries_then_succeeds(photos10, dummy_hosting, fake_settings, monkeypatch):
    behavior = {url_for(7): [TransientError("5xx")]}
    client = FakeClient(behavior=behavior)
    monkeypatch.setattr(publisher, "_client", lambda s: client)
    res = publisher.publish(fake_settings)
    assert res.status == "COMPLETED"


def test_raw_url_hosting(photos10, fake_settings, monkeypatch):
    # con media_base_url no usa tunel: arma URLs raw estables
    from dataclasses import replace
    s = replace(fake_settings, media_base_url="https://raw.example/photos")
    client = FakeClient()
    monkeypatch.setattr(publisher, "_client", lambda _s: client)
    res = publisher.publish(s)
    assert res.status == "COMPLETED"
    assert res.published == 10
    assert all(u.startswith("https://raw.example/photos/") for u in client.published)


def test_image_rejected_retries_then_succeeds(photos10, dummy_hosting, fake_settings, monkeypatch):
    # "Only photo or video..." suele ser fetch transitorio del tunel -> debe reintentar
    behavior = {url_for(1): [ImageRejectedError("Only photo or video", code=100, subcode=2207009)]}
    client = FakeClient(behavior=behavior)
    monkeypatch.setattr(publisher, "_client", lambda s: client)
    res = publisher.publish(fake_settings)
    assert res.status == "COMPLETED"
    assert res.published == 10
    assert client._calls[url_for(1)] == 2   # fallo 1 + exito al reintentar


def test_auth_error_stops_and_no_retry(photos10, dummy_hosting, fake_settings, monkeypatch):
    # seq 1 da AuthError: no se reintenta y corta la secuencia
    behavior = {url_for(1): [AuthError("token invalido", code=190)]}
    client = FakeClient(behavior=behavior)
    monkeypatch.setattr(publisher, "_client", lambda s: client)
    res = publisher.publish(fake_settings)
    assert res.status == "FAILED"
    assert len(client.published) == 0  # corto en la primera
    assert client._calls[url_for(1)] == 1  # un solo intento, sin reintentos
