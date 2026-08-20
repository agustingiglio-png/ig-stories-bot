"""Fixtures: DB temporal, fotos temporales y un cliente de Instagram falso.

Ningun test toca la red ni la API real de Meta.
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from igstories import db, images, publisher  # noqa: E402
from igstories.config import Settings  # noqa: E402


@pytest.fixture
def tmp_env(tmp_path, monkeypatch):
    """Redirige DB y carpeta de fotos a un area temporal."""
    state_dir = tmp_path / "state"
    photos_dir = tmp_path / "photos"
    state_dir.mkdir()
    photos_dir.mkdir()

    monkeypatch.setattr(db, "STATE_DIR", state_dir)
    monkeypatch.setattr(db, "DB_PATH", state_dir / "app.sqlite")
    monkeypatch.setattr(images, "PHOTOS_DIR", photos_dir)
    monkeypatch.setattr(publisher, "TMP_DIR", tmp_path / "serve")
    db.init_db()
    return {"state": state_dir, "photos": photos_dir, "tmp": tmp_path}


def make_photo(photos_dir: Path, name: str, size=(1080, 1920), color=(120, 30, 200)):
    img = Image.new("RGB", size, color)
    img.save(photos_dir / name, "JPEG", quality=85)


@pytest.fixture
def photos10(tmp_env):
    for i in range(1, 11):
        make_photo(tmp_env["photos"], f"{i:02d}.jpg", color=(i * 20 % 255, 60, 120))
    return tmp_env


@pytest.fixture
def dummy_hosting(monkeypatch):
    """Reemplaza tunel real + materialize por nombres deterministas (seq-NN.jpg)."""
    def fake_materialize(photos, out_dir):
        out_dir.mkdir(parents=True, exist_ok=True)
        result = []
        for p in photos:
            path = out_dir / f"seq-{p.seq:02d}.jpg"
            path.write_bytes(b"\xff\xd8\xff\xd9")  # jpeg minimo ficticio
            result.append((p, path))
        return result

    @contextlib.contextmanager
    def fake_urls(serve_dir, filenames, cloudflared_bin="", timeout=45):
        yield {fn: f"https://fake.local/{fn}" for fn in filenames}

    monkeypatch.setattr(publisher, "materialize", fake_materialize)
    monkeypatch.setattr(publisher, "public_urls", fake_urls)


def url_for(seq: int) -> str:
    return f"https://fake.local/seq-{seq:02d}.jpg"


class FakeClient:
    """Cliente falso configurable. behavior[seq] = lista de excepciones/valor por intento."""

    def __init__(self, behavior=None, media_prefix="mid"):
        self.ig_user_id = "123"
        self.behavior = behavior or {}
        self._calls = {}
        self.media_prefix = media_prefix
        self.published = []
        self.published_kinds = []   # True si fue video, por orden de publicacion

    def content_publishing_limit(self):
        return {"data": [{"quota_usage": 0}]}

    def get_account(self):
        return {"username": "test", "account_type": "BUSINESS", "user_id": "123"}

    def publish_story(self, media_url, is_video=False):
        # cuenta el intento por url (una url distinta por seq via filename)
        n = self._calls.get(media_url, 0)
        self._calls[media_url] = n + 1
        seq_actions = self.behavior.get(media_url)
        if seq_actions and n < len(seq_actions):
            action = seq_actions[n]
            if isinstance(action, Exception):
                raise action
        mid = f"{self.media_prefix}-{len(self.published)+1}"
        self.published.append(media_url)
        self.published_kinds.append(is_video)
        return mid


@pytest.fixture
def fake_settings():
    return Settings(access_token="TOK", ig_user_id="123", app_secret="",
                    graph_version="v23.0", cloudflared_bin="/bin/true")
