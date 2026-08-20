"""Validacion de imagenes: faltantes, invalidas, PNG->JPEG, tamaño."""
from __future__ import annotations

import pytest
from PIL import Image

from igstories.images import ImageError, build_photos, discover
from tests.conftest import make_photo


def test_no_photos_fails(tmp_env):
    with pytest.raises(ImageError):
        build_photos()


def test_valid_photos(photos10):
    photos = build_photos()
    assert len(photos) == 10
    assert [p.seq for p in photos] == list(range(1, 11))


def test_deterministic_order(tmp_env):
    make_photo(tmp_env["photos"], "03.jpg")
    make_photo(tmp_env["photos"], "01.jpg")
    make_photo(tmp_env["photos"], "02.jpg")
    names = [p.name for p in discover()]
    assert names == ["01.jpg", "02.jpg", "03.jpg"]


def test_png_is_converted(tmp_env):
    img = Image.new("RGBA", (1080, 1920), (10, 20, 30, 128))
    img.save(tmp_env["photos"] / "01.png")
    photos = build_photos()
    assert photos[0].is_png is True
    # el sha corresponde al JPEG normalizado (se pudo generar sin error)
    assert len(photos[0].sha256) == 64


def test_corrupt_file_fails(tmp_env):
    (tmp_env["photos"] / "01.jpg").write_bytes(b"no soy una imagen")
    with pytest.raises(ImageError):
        build_photos()


def test_too_narrow_fails(tmp_env):
    make_photo(tmp_env["photos"], "01.jpg", size=(100, 200))  # < MIN_WIDTH
    with pytest.raises(ImageError):
        build_photos()


def test_non_vertical_warns(tmp_env):
    make_photo(tmp_env["photos"], "01.jpg", size=(1080, 1080))  # cuadrada
    photos = build_photos()
    assert photos[0].warnings  # avisa que no es 9:16
