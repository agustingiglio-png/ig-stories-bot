"""Descubrimiento, validacion y normalizacion de las fotos y videos.

- Orden determinista: por nombre de archivo (01, 02, ... 10).
- Imagenes: .jpg/.jpeg/.png de entrada; PNG se convierte a JPEG porque la API
  de Instagram SOLO publica JPEG.
- Videos: .mp4/.mov; se publican tal cual (la API acepta MP4/MOV para Stories).
- Se valida ANTES de publicar: si algo no cumple, se falla temprano y NO se
  publica nada (nada de publicaciones parciales por config incompleta).
"""
from __future__ import annotations

import hashlib
import io
import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps

from .config import (ALLOWED_INPUT_EXT, IMAGE_EXT, MAX_IMAGE_BYTES,
                     MAX_PHOTOS, MAX_VIDEO_BYTES, MAX_VIDEO_SECONDS, MAX_WIDTH,
                     MIN_PHOTOS, MIN_WIDTH, PHOTOS_DIR, VIDEO_EXT)


@dataclass
class Photo:
    """Un item de media (imagen o video) listo para publicar como Story."""
    seq: int
    src: Path            # archivo original en photos/
    filename: str
    kind: str            # 'IMAGE' | 'VIDEO'
    sha256: str          # huella del contenido que se publica
    warnings: list = field(default_factory=list)
    width: int | None = None
    height: int | None = None
    is_png: bool = False

    @property
    def is_video(self) -> bool:
        return self.kind == "VIDEO"

    @property
    def out_ext(self) -> str:
        return ".jpg" if self.kind == "IMAGE" else self.src.suffix.lower()


class ImageError(Exception):
    """Error de validacion de media (permanente: no reintentar)."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXT:
        return "VIDEO"
    if ext in IMAGE_EXT:
        return "IMAGE"
    return "OTHER"


def discover() -> list[Path]:
    """Lista ordenada y determinista de archivos candidatos en photos/."""
    if not PHOTOS_DIR.exists():
        return []
    files = [
        p for p in PHOTOS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in ALLOWED_INPUT_EXT
    ]
    return sorted(files, key=lambda p: p.name.lower())


# --- imagenes ----------------------------------------------------------------
def _normalized_bytes(path: Path) -> tuple[bytes, int, int, bool, list[str]]:
    """Devuelve (jpeg_bytes, width, height, was_png, warnings).

    Convierte a JPEG (unico formato que acepta la API). Aplana transparencia.
    NO recorta ni fuerza aspecto: Instagram ajusta el 9:16 de la Story.
    """
    warnings: list[str] = []
    with Image.open(path) as im:
        was_png = (im.format or "").upper() == "PNG" or path.suffix.lower() == ".png"
        # Aplicar la orientacion EXIF FISICAMENTE (rota los pixeles y limpia el tag).
        # Sin esto, las fotos verticales del celu se subirian "de costado".
        im = ImageOps.exif_transpose(im)
        im.load()
        width, height = im.size

        if im.mode in ("RGBA", "LA", "P"):
            background = Image.new("RGB", im.size, (255, 255, 255))
            rgba = im.convert("RGBA")
            background.paste(rgba, mask=rgba.split()[-1])
            im = background
        elif im.mode != "RGB":
            im = im.convert("RGB")

        if width < MIN_WIDTH:
            raise ImageError(
                f"{path.name}: ancho {width}px < minimo {MIN_WIDTH}px que exige Instagram"
            )
        if width > MAX_WIDTH:
            warnings.append(
                f"{path.name}: ancho {width}px > {MAX_WIDTH}px; se reduce a {MAX_WIDTH}px"
            )
            new_h = round(height * MAX_WIDTH / width)
            im = im.resize((MAX_WIDTH, new_h), Image.LANCZOS)
            width, height = im.size

        ratio = height / width if width else 0
        if not (1.2 <= ratio <= 2.2):
            warnings.append(
                f"{path.name}: relacion {width}x{height} no es vertical 9:16; "
                "Instagram puede recortar o poner bordes"
            )

        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=90, optimize=True)
        data = buf.getvalue()

    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(
            f"{path.name}: pesa {len(data)//1024} KB > {MAX_IMAGE_BYTES//1024} KB permitido"
        )
    return data, width, height, was_png, warnings


# --- videos ------------------------------------------------------------------
def _probe_duration(path: Path) -> float | None:
    """Duracion en segundos via ffprobe si esta instalado; None si no se puede."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        out = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return None


def _validate_video(path: Path) -> tuple[str, list[str]]:
    """Valida un video de Story. Devuelve (sha256, warnings)."""
    warnings: list[str] = []
    size = path.stat().st_size
    if size == 0:
        raise ImageError(f"{path.name}: archivo de video vacio")
    if size > MAX_VIDEO_BYTES:
        raise ImageError(
            f"{path.name}: pesa {size//(1024*1024)} MB > {MAX_VIDEO_BYTES//(1024*1024)} MB permitido"
        )
    dur = _probe_duration(path)
    if dur is not None:
        if dur > MAX_VIDEO_SECONDS + 0.5:
            raise ImageError(
                f"{path.name}: dura {dur:.0f}s > {MAX_VIDEO_SECONDS}s (limite de Stories)"
            )
    else:
        warnings.append(
            f"{path.name}: no se pudo verificar la duracion (instalá ffmpeg para chequearla); "
            f"Instagram la rechazara si supera {MAX_VIDEO_SECONDS}s"
        )
    return _sha256_file(path), warnings


# --- API publica del modulo --------------------------------------------------
def build_photos() -> list[Photo]:
    """Valida todos los medios y devuelve la lista lista para publicar.

    Lanza ImageError si algo esta mal (cantidad, formato, tamaño, duracion...).
    """
    files = discover()
    if len(files) < MIN_PHOTOS:
        raise ImageError(
            f"No hay medios validos en {PHOTOS_DIR} (encontrados: {len(files)}). "
            "Poné al menos una imagen .jpg/.png o un video .mp4/.mov."
        )
    if len(files) > MAX_PHOTOS:
        raise ImageError(
            f"Demasiados archivos ({len(files)}); el maximo de seguridad es {MAX_PHOTOS}."
        )

    items: list[Photo] = []
    for i, path in enumerate(files, start=1):
        kind = _kind_of(path)
        if kind == "VIDEO":
            try:
                sha, warns = _validate_video(path)
            except ImageError:
                raise
            except Exception as e:
                raise ImageError(f"{path.name}: no se pudo leer el video ({e})")
            items.append(Photo(seq=i, src=path, filename=path.name, kind="VIDEO",
                               sha256=sha, warnings=warns))
        else:
            try:
                data, w, h, was_png, warns = _normalized_bytes(path)
            except ImageError:
                raise
            except Exception as e:
                raise ImageError(f"{path.name}: no se pudo leer como imagen ({e})")
            items.append(Photo(seq=i, src=path, filename=path.name, kind="IMAGE",
                               sha256=_sha256_bytes(data), warnings=warns,
                               width=w, height=h, is_png=was_png))
    return items


# alias explicito para quien prefiera un nombre generico
build_media = build_photos


def materialize(photos: list[Photo], out_dir: Path) -> list[tuple[Photo, Path]]:
    """Escribe los medios normalizados en out_dir con nombres UUID (no adivinables).

    - Imagenes: JPEG normalizado (uuid.jpg).
    - Videos: copia tal cual (uuid + extension original).
    Devuelve [(photo, path)]. Estos son los archivos que servira el tunel.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    result: list[tuple[Photo, Path]] = []
    for p in photos:
        name = f"{uuid.uuid4().hex}{p.out_ext}"
        target = out_dir / name
        if p.is_video:
            shutil.copy2(p.src, target)
        else:
            data, _, _, _, _ = _normalized_bytes(p.src)
            target.write_bytes(data)
        result.append((p, target))
    return result
