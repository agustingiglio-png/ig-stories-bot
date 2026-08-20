"""Configuracion central: paths, timezone, y carga de variables de entorno.

Nunca se hardcodean secretos aca: todo sale de variables de entorno / .env.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv es opcional en la nube (usa Secrets como env vars)
    def load_dotenv(*_a, **_k):  # type: ignore
        return False

# --- Paths del proyecto (todo relativo a la raiz del repo) -------------------
ROOT = Path(__file__).resolve().parent.parent
PHOTOS_DIR = ROOT / "photos"
STATE_DIR = ROOT / "state"
LOGS_DIR = ROOT / "logs"
DB_PATH = STATE_DIR / "app.sqlite"

# --- Timezone: SIEMPRE Argentina, jamas la del servidor ----------------------
TZ = ZoneInfo("America/Argentina/Buenos_Aires")
PUBLISH_HOUR = 13          # 13:00 hora Argentina
PUBLISH_MINUTE = 0

# --- Reglas de contenido -----------------------------------------------------
EXPECTED_PHOTOS = 10       # cantidad esperada (informativa; ver ALLOW_ANY_COUNT)
MIN_PHOTOS = 1
MAX_PHOTOS = 20            # tope de seguridad
IMAGE_EXT = {".jpg", ".jpeg", ".png"}           # PNG se convierte a JPEG
VIDEO_EXT = {".mp4", ".mov"}                     # video de Story (MP4/MOV)
ALLOWED_INPUT_EXT = IMAGE_EXT | VIDEO_EXT
MAX_IMAGE_BYTES = 8 * 1024 * 1024               # 8 MB, limite de Meta para imagenes
MAX_VIDEO_BYTES = 100 * 1024 * 1024             # 100 MB para video de Story
MAX_VIDEO_SECONDS = 60                          # las Stories aceptan hasta 60s
# Instagram descarta imagenes fuera de estos anchos.
MIN_WIDTH = 320
MAX_WIDTH = 1440

# Token: refrescar cuando le queden menos de estos dias de vida (~60 total).
TOKEN_REFRESH_BEFORE_DAYS = 10


def load_env() -> None:
    """Carga .env si existe (local). En la nube las vars ya vienen del entorno."""
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


@dataclass(frozen=True)
class Settings:
    access_token: str
    ig_user_id: str
    app_secret: str
    graph_version: str
    cloudflared_bin: str

    @property
    def has_token(self) -> bool:
        return bool(self.access_token)


def get_settings() -> Settings:
    load_env()
    return Settings(
        access_token=os.environ.get("IG_ACCESS_TOKEN", "").strip(),
        ig_user_id=os.environ.get("IG_USER_ID", "").strip(),
        app_secret=os.environ.get("IG_APP_SECRET", "").strip(),
        graph_version=os.environ.get("GRAPH_VERSION", "v23.0").strip(),
        cloudflared_bin=os.environ.get("CLOUDFLARED_BIN", "").strip(),
    )


def now_ar() -> datetime:
    """Ahora, en hora Argentina (independiente del reloj del servidor)."""
    return datetime.now(TZ)


def today_ar() -> date:
    """La fecha de HOY segun Argentina."""
    return now_ar().date()


def next_publish_dt(reference: datetime | None = None) -> datetime:
    """Proxima ocurrencia de las 13:00 ART a partir de `reference` (o ahora)."""
    ref = reference or now_ar()
    candidate = ref.replace(hour=PUBLISH_HOUR, minute=PUBLISH_MINUTE, second=0, microsecond=0)
    if candidate <= ref:
        from datetime import timedelta
        candidate = candidate + timedelta(days=1)
    return candidate


def mask(secret: str) -> str:
    """Nunca imprimir tokens completos. Devuelve algo como 'IGQ...a1b2' o '(vacio)'."""
    if not secret:
        return "(vacio)"
    if len(secret) <= 8:
        return "****"
    return f"{secret[:3]}...{secret[-4:]}"
