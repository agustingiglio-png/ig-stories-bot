"""Clasificacion de errores de la API y fallos de configuracion."""
from __future__ import annotations

import pytest

from igstories import publisher
from igstories.config import Settings
from igstories.instagram import (AuthError, ImageRejectedError, InstagramClient,
                                 PermanentError, RateLimitError, TransientError)


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.ok = 200 <= status < 300
        self.text = str(payload)

    def json(self):
        return self._payload


def _classify(status, error):
    c = InstagramClient("TOK", "123")
    return c._classify(_Resp(status, {"error": error}))


def test_classify_rate_limit_429():
    assert isinstance(_classify(429, {"message": "slow down"}), RateLimitError)


def test_classify_rate_limit_code():
    assert isinstance(_classify(400, {"message": "limit", "code": 4}), RateLimitError)


def test_classify_auth():
    assert isinstance(_classify(400, {"message": "bad token", "code": 190}), AuthError)


def test_classify_server_transient():
    assert isinstance(_classify(500, {"message": "oops"}), TransientError)


def test_classify_image_rejected():
    err = {"message": "media error", "code": 100, "error_subcode": 2207052}
    assert isinstance(_classify(400, err), ImageRejectedError)


def test_classify_permanent_default():
    assert isinstance(_classify(400, {"message": "weird", "code": 100}), PermanentError)


def test_publish_without_token_fails(photos10, dummy_hosting):
    settings = Settings(access_token="", ig_user_id="", app_secret="",
                        graph_version="v23.0", cloudflared_bin="/bin/true", media_base_url="")
    res = publisher.publish(settings)
    assert res.status == "FAILED"
    assert "IG_ACCESS_TOKEN" in res.reason
