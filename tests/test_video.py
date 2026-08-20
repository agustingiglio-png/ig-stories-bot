"""Soporte de video: deteccion, validacion y ruteo a video_url al publicar."""
from __future__ import annotations

import pytest

from igstories import db, publisher
from igstories.images import ImageError, build_photos
from igstories.config import MAX_VIDEO_BYTES
from tests.conftest import FakeClient, make_photo


def test_video_detected(tmp_env):
    (tmp_env["photos"] / "01.mp4").write_bytes(b"\x00" * 4096)
    photos = build_photos()
    assert photos[0].is_video is True
    assert photos[0].kind == "VIDEO"
    assert photos[0].out_ext == ".mp4"


def test_mov_detected(tmp_env):
    (tmp_env["photos"] / "01.mov").write_bytes(b"\x00" * 4096)
    photos = build_photos()
    assert photos[0].kind == "VIDEO"


def test_empty_video_fails(tmp_env):
    (tmp_env["photos"] / "01.mp4").write_bytes(b"")
    with pytest.raises(ImageError):
        build_photos()


def test_oversized_video_fails(tmp_env, monkeypatch):
    # simula un video enorme sin escribir 100MB reales
    (tmp_env["photos"] / "01.mp4").write_bytes(b"\x00" * 1024)
    monkeypatch.setattr("igstories.images.MAX_VIDEO_BYTES", 512)
    with pytest.raises(ImageError):
        build_photos()


def test_mixed_image_and_video_publish(tmp_env, dummy_hosting, fake_settings, monkeypatch):
    make_photo(tmp_env["photos"], "01.jpg")
    (tmp_env["photos"] / "02.mp4").write_bytes(b"\x00" * 8192)
    monkeypatch.setattr(publisher.time, "sleep", lambda *_: None)

    client = FakeClient()
    monkeypatch.setattr(publisher, "_client", lambda s: client)
    res = publisher.publish(fake_settings)

    assert res.status == "COMPLETED"
    assert res.published == 2
    # seq 01 = imagen (is_video False), seq 02 = video (is_video True)
    assert client.published_kinds == [False, True]
