"""Orquestacion de la publicacion diaria: idempotencia, reintentos y reanudacion.

Garantias clave:
- Si el run del dia ya esta COMPLETED -> NO republica (idempotente).
- Cada Story se marca PUBLISHED apenas se confirma -> si el proceso muere a mitad,
  al reanudar solo se publican las que faltan (nunca duplica).
- Validacion total ANTES de empezar: si falta o sobra algo, no se publica nada.
- Reintentos solo para errores realmente transitorios, con backoff.
"""
from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import db
from .config import ROOT, Settings, TOKEN_REFRESH_BEFORE_DAYS, today_ar
from .hosting import HostingError, public_urls
from .images import ImageError, Photo, build_photos, materialize
from .instagram import (ApiError, AuthError, ImageRejectedError, InstagramClient,
                        PermanentError, RateLimitError, TransientError)
from .logging_setup import get_logger

TMP_DIR = ROOT / ".tmp" / "serve"

# Backoff (segundos) por categoria de error.
_RETRY_TRANSIENT = [5, 15, 45]
_RETRY_RATELIMIT = [60, 180, 300]


@dataclass
class Result:
    day: str
    status: str
    published: int = 0
    total: int = 0
    skipped: bool = False
    reason: str = ""
    errors: list[str] = field(default_factory=list)


class ConfigError(Exception):
    """Config incompleta (token/credenciales). Permanente."""


def _client(settings: Settings) -> InstagramClient:
    if not settings.has_token:
        raise ConfigError("Falta IG_ACCESS_TOKEN. Configuralo en .env o en los Secrets.")
    uid = settings.ig_user_id or db.get_meta("ig_user_id") or ""
    client = InstagramClient(settings.access_token, uid, settings.graph_version)
    if not client.ig_user_id:
        client.resolve_user_id()
        db.set_meta("ig_user_id", client.ig_user_id)
    return client


def _publish_one_with_retries(client: InstagramClient, media_url: str,
                              is_video: bool = False) -> str:
    """Publica una Story reintentando solo errores transitorios/rate-limit."""
    log = get_logger()
    attempt = 0
    while True:
        try:
            return client.publish_story(media_url, is_video=is_video)
        except RateLimitError as e:
            if attempt >= len(_RETRY_RATELIMIT):
                raise
            wait = _RETRY_RATELIMIT[attempt]
            log.warning("Rate limit (429/%s). Reintento en %ds", e.code, wait)
        except TransientError as e:
            if attempt >= len(_RETRY_TRANSIENT):
                raise
            wait = _RETRY_TRANSIENT[attempt]
            log.warning("Error temporal (%s). Reintento en %ds", e, wait)
        # Auth/Permanent/ImageRejected: NO se capturan -> propagan sin reintentar.
        attempt += 1
        time.sleep(wait)


def publish(settings: Settings, force_day: str | None = None) -> Result:
    """Publica las Stories del dia. Respeta idempotencia y skips."""
    log = get_logger()
    db.init_db()
    day = force_day or today_ar().isoformat()
    log.info("Iniciando publicacion diaria para %s (hora Argentina)", day)

    # 1) Idempotencia: run ya completado.
    run = db.get_run(day)
    if run and run["status"] == "COMPLETED":
        log.info("El dia %s ya estaba COMPLETED. No se republica.", day)
        return Result(day, "COMPLETED", reason="ya publicado hoy")

    # 2) Skip del dia.
    if db.is_skipped(day):
        reason = "skip configurado para hoy"
        log.info("Dia %s OMITIDO: %s", day, reason)
        db.set_run_status(day, "SKIPPED", reason=reason, finished=True)
        return Result(day, "SKIPPED", skipped=True, reason=reason)

    # 3) Validacion total ANTES de tocar la API (falla temprano).
    try:
        photos = build_photos()
    except ImageError as e:
        log.error("Config de imagenes invalida: %s", e)
        db.set_run_status(day, "FAILED", error=str(e), finished=True)
        return Result(day, "FAILED", reason=str(e), errors=[str(e)])

    for p in photos:
        for w in p.warnings:
            log.warning("Aviso: %s", w)
    log.info("%d imagenes encontradas y validadas", len(photos))

    try:
        client = _client(settings)
    except (ConfigError, AuthError) as e:
        log.error("Credenciales/permisos: %s", e)
        db.set_run_status(day, "FAILED", error=str(e), finished=True)
        return Result(day, "FAILED", reason=str(e), errors=[str(e)])

    # 4) Filas de stories (idempotencia por imagen) + marcar RUNNING.
    db.ensure_story_rows(day, [(p.seq, p.filename, p.sha256) for p in photos])
    db.start_run(day)

    # 5) Chequeo de cuota (informativo).
    try:
        limit = client.content_publishing_limit()
        usage = (limit.get("data") or [{}])[0].get("quota_usage", "?")
        log.info("Cuota de publicacion usada en 24h: %s", usage)
    except ApiError as e:
        log.warning("No se pudo leer content_publishing_limit: %s", e)

    # 6) Solo publicar las que faltan (resume).
    stories = db.get_stories(day)
    pending = [s for s in stories if s["status"] != "PUBLISHED"]
    by_seq = {p.seq: p for p in photos}
    if not pending:
        log.info("No hay stories pendientes; marcando COMPLETED.")
        db.set_run_status(day, "COMPLETED", finished=True)
        return Result(day, "COMPLETED", published=len(stories), total=len(stories))

    result = Result(day, "RUNNING", total=len(stories),
                    published=len(stories) - len(pending))

    if TMP_DIR.exists():
        shutil.rmtree(TMP_DIR, ignore_errors=True)
    served = materialize([by_seq[s["seq"]] for s in pending], TMP_DIR)
    fn_by_seq = {photo.seq: path.name for photo, path in served}
    filenames = [path.name for _, path in served]

    try:
        with public_urls(TMP_DIR, filenames, settings.cloudflared_bin) as urls:
            for s in pending:
                seq = s["seq"]
                fname = fn_by_seq[seq]
                media = by_seq[seq]
                orig = media.filename
                log.info("Publicando %s (seq %02d, %s)", orig, seq, media.kind)
                try:
                    media_id = _publish_one_with_retries(client, urls[fname],
                                                         is_video=media.is_video)
                    db.mark_story_published(day, seq, media_id)
                    result.published += 1
                    log.info("Story %02d publicada (media_id=%s)", seq, media_id)
                except AuthError as e:
                    msg = f"Auth/permiso al publicar seq {seq}: {e}"
                    log.error(msg)
                    db.mark_story_failed(day, seq, str(e))
                    result.errors.append(msg)
                    break  # sin token valido no tiene sentido seguir
                except ImageRejectedError as e:
                    msg = f"Imagen rechazada seq {seq} ({orig}): {e}"
                    log.error(msg)
                    db.mark_story_failed(day, seq, str(e))
                    result.errors.append(msg)
                    continue  # sigue con las demas
                except (PermanentError, RateLimitError, TransientError) as e:
                    msg = f"Fallo seq {seq} ({orig}): {e}"
                    log.error(msg)
                    db.mark_story_failed(day, seq, str(e))
                    result.errors.append(msg)
                    continue
    except HostingError as e:
        msg = f"No se pudo montar el tunel publico: {e}"
        log.error(msg)
        db.set_run_status(day, "FAILED", error=msg, finished=True)
        result.status = "FAILED"
        result.errors.append(msg)
        return result
    finally:
        shutil.rmtree(TMP_DIR, ignore_errors=True)

    # 7) Estado final.
    stories = db.get_stories(day)
    published = [s for s in stories if s["status"] == "PUBLISHED"]
    if len(published) == len(stories):
        db.set_run_status(day, "COMPLETED", finished=True)
        result.status = "COMPLETED"
        log.info("Publicacion completada: %d/%d stories", len(published), len(stories))
    else:
        db.set_run_status(day, "FAILED",
                          error=f"{len(published)}/{len(stories)} publicadas", finished=True)
        result.status = "FAILED"
        log.warning("Publicacion PARCIAL: %d/%d. Reejecutá 'publish' para reanudar.",
                    len(published), len(stories))
    return result


def dry_run(settings: Settings) -> Result:
    """Simula todo SIN publicar: config, credenciales, TZ, skip, imagenes, Meta, tunel."""
    import shutil as _sh

    log = get_logger()
    db.init_db()
    day = today_ar().isoformat()
    errors: list[str] = []
    log.info("== DRY-RUN (no se publica nada) para %s ==", day)

    # timezone
    from .config import now_ar, next_publish_dt
    log.info("Hora Argentina ahora: %s", now_ar().strftime("%Y-%m-%d %H:%M:%S %Z"))
    log.info("Proxima publicacion 13:00 ART: %s", next_publish_dt().strftime("%Y-%m-%d %H:%M"))

    # skip
    if db.is_skipped(day):
        log.info("Estado del dia: OMITIDO (skip configurado). No publicaria.")
    else:
        log.info("Estado del dia: HABILITADO")

    # idempotencia
    run = db.get_run(day)
    if run and run["status"] == "COMPLETED":
        log.info("El dia ya esta COMPLETED: en real no republicaria.")

    # imagenes
    try:
        photos = build_photos()
        n_img = sum(1 for p in photos if not p.is_video)
        n_vid = sum(1 for p in photos if p.is_video)
        log.info("Medios: %d validos (%d imagenes, %d videos)", len(photos), n_img, n_vid)
        for p in photos:
            if p.is_video:
                log.info("  seq %02d  %s  [VIDEO]", p.seq, p.filename)
            else:
                flag = " (PNG->JPEG)" if p.is_png else ""
                log.info("  seq %02d  %s  %dx%d%s", p.seq, p.filename, p.width, p.height, flag)
            for w in p.warnings:
                log.warning("  aviso: %s", w)
    except ImageError as e:
        errors.append(f"imagenes: {e}")
        log.error("Imagenes invalidas: %s", e)

    # credenciales + conexion a Meta
    if not settings.has_token:
        errors.append("falta IG_ACCESS_TOKEN")
        log.error("Falta IG_ACCESS_TOKEN")
    else:
        try:
            client = _client(settings)
            acc = client.get_account()
            log.info("Cuenta Meta OK: @%s (%s), user_id=%s",
                     acc.get("username", "?"), acc.get("account_type", "?"), client.ig_user_id)
            limit = client.content_publishing_limit()
            usage = (limit.get("data") or [{}])[0].get("quota_usage", "?")
            log.info("Cuota usada 24h: %s", usage)
        except ApiError as e:
            errors.append(f"meta: {e}")
            log.error("Fallo verificando con Meta: %s", e)

    # tunel disponible
    bin_ok = settings.cloudflared_bin or _sh.which("cloudflared")
    if bin_ok:
        log.info("cloudflared disponible: %s", bin_ok)
    else:
        errors.append("cloudflared no instalado")
        log.error("cloudflared no encontrado (necesario para exponer las fotos)")

    status = "OK" if not errors else "FAILED"
    log.info("== DRY-RUN %s ==", status)
    return Result(day, status, total=0, reason="dry-run", errors=errors)


def refresh_token_if_needed(settings: Settings, force: bool = False) -> dict | None:
    """Refresca el token long-lived si le quedan pocos dias. Devuelve el nuevo token dict."""
    from datetime import datetime, timezone

    from .instagram import refresh_long_lived_token
    log = get_logger()
    db.init_db()
    last = db.get_meta("token_expires_at")
    if not force and last:
        try:
            expires = datetime.fromisoformat(last)
            days_left = (expires - datetime.now(timezone.utc)).days
            if days_left > TOKEN_REFRESH_BEFORE_DAYS:
                log.info("Token con %d dias de vida; no hace falta refrescar.", days_left)
                return None
        except ValueError:
            pass
    data = refresh_long_lived_token(settings.access_token, settings.graph_version)
    from datetime import timedelta
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 0)))
    db.set_meta("token_expires_at", expires_at.isoformat())
    db.set_meta("token_refreshed_at", datetime.now(timezone.utc).isoformat())
    log.info("Token refrescado. Nueva expiracion: %s (UTC)", expires_at.date())
    return data
