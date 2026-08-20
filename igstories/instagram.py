"""Cliente de la API oficial de Instagram (Instagram API with Instagram Login).

Docs verificadas 2026-08-19:
  https://developers.facebook.com/docs/instagram-platform/content-publishing/

Flujo de una Story:
  1) POST {graph}/{ig_id}/media    con image_url + media_type=STORIES  -> creation_id
  2) (poll)  GET  {graph}/{creation_id}?fields=status_code             -> FINISHED
  3) POST {graph}/{ig_id}/media_publish  con creation_id               -> media_id

Host: https://graph.instagram.com   (variante Instagram Login, sin Facebook Page)
Scopes: instagram_business_basic + instagram_business_content_publish
"""
from __future__ import annotations

import time
from typing import Any

import requests

from .logging_setup import get_logger, register_secret

GRAPH_HOST = "https://graph.instagram.com"


# --- Taxonomia de errores (define si se reintenta o no) ----------------------
class ApiError(Exception):
    def __init__(self, message: str, *, code: int | None = None, subcode: int | None = None):
        super().__init__(message)
        self.code = code
        self.subcode = subcode


class AuthError(ApiError):
    """Token invalido/expirado o permisos faltantes. PERMANENTE: no reintentar."""


class RateLimitError(ApiError):
    """HTTP 429 o error 4/17/32/613. TRANSITORIO: reintentar con backoff largo."""


class TransientError(ApiError):
    """Timeout, 5xx, error temporal de Meta. TRANSITORIO: reintentar."""


class ImageRejectedError(ApiError):
    """Meta rechazo la imagen (formato/aspecto/descarga). PERMANENTE para esa imagen."""


class PermanentError(ApiError):
    """Cualquier otro error definitivo. No reintentar."""


# codes de error de Meta que son rate limit
_RATE_CODES = {4, 17, 32, 613}
_AUTH_CODES = {190, 102, 10, 200, 3, 803}


class InstagramClient:
    def __init__(self, access_token: str, ig_user_id: str, graph_version: str = "v23.0"):
        self.token = access_token
        self.ig_user_id = ig_user_id
        self.version = graph_version
        self.session = requests.Session()
        register_secret(access_token)
        self.log = get_logger()

    # --- helpers de red ------------------------------------------------------
    def _url(self, path: str) -> str:
        return f"{GRAPH_HOST}/{self.version}/{path.lstrip('/')}"

    def _classify(self, resp: requests.Response) -> ApiError:
        try:
            err = resp.json().get("error", {})
        except Exception:
            err = {}
        msg = err.get("message", resp.text[:300])
        code = err.get("code")
        subcode = err.get("error_subcode")

        if resp.status_code == 429 or code in _RATE_CODES:
            return RateLimitError(msg, code=code, subcode=subcode)
        if resp.status_code in (401, 403) or code in _AUTH_CODES:
            return AuthError(msg, code=code, subcode=subcode)
        if resp.status_code >= 500:
            return TransientError(msg, code=code, subcode=subcode)
        # 2207xx: errores de media (imagen no descargable / formato)
        if code == 36003 or (subcode and 2207000 <= int(subcode) <= 2207100):
            return ImageRejectedError(msg, code=code, subcode=subcode)
        return PermanentError(msg, code=code, subcode=subcode)

    def _request(self, method: str, path: str, **params) -> dict[str, Any]:
        params["access_token"] = self.token
        url = self._url(path)
        try:
            resp = self.session.request(method, url, data=params if method == "POST" else None,
                                        params=params if method == "GET" else None, timeout=60)
        except requests.RequestException as e:
            raise TransientError(f"Fallo de red: {e}")
        if not resp.ok:
            raise self._classify(resp)
        try:
            return resp.json()
        except Exception:
            raise TransientError("Respuesta no-JSON de Meta")

    # --- endpoints -----------------------------------------------------------
    def resolve_user_id(self) -> str:
        """Devuelve el user_id de la cuenta del token (y lo cachea en el cliente)."""
        data = self._request("GET", "me", fields="user_id,username")
        uid = str(data.get("user_id") or data.get("id") or "")
        if not uid:
            raise AuthError("No se pudo resolver el user_id desde /me")
        self.ig_user_id = uid
        return uid

    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "me", fields="user_id,username,account_type")

    def content_publishing_limit(self) -> dict[str, Any]:
        return self._request("GET", f"{self.ig_user_id}/content_publishing_limit",
                             fields="quota_usage,config")

    def create_story_container(self, media_url: str, is_video: bool = False) -> str:
        params = {"media_type": "STORIES"}
        if is_video:
            params["video_url"] = media_url
        else:
            params["image_url"] = media_url
        data = self._request("POST", f"{self.ig_user_id}/media", **params)
        cid = data.get("id")
        if not cid:
            raise PermanentError(f"media sin 'id' en la respuesta: {data}")
        return str(cid)

    def wait_container_ready(self, creation_id: str, is_video: bool = False,
                             attempts: int | None = None, delay: float | None = None) -> None:
        """Espera a que el container este FINISHED antes de publicar.

        Los videos tardan mas en procesar, asi que esperamos mucho mas tiempo.
        """
        if attempts is None:
            attempts = 40 if is_video else 10       # ~4 min video / ~30s imagen
        if delay is None:
            delay = 6.0 if is_video else 3.0
        for _ in range(attempts):
            data = self._request("GET", creation_id, fields="status_code,status")
            status = data.get("status_code")
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise ImageRejectedError(f"Container en ERROR: {data.get('status')}")
            if status == "EXPIRED":
                raise TransientError("Container EXPIRED antes de publicar")
            time.sleep(delay)
        raise TransientError(f"Container {creation_id} no llego a FINISHED a tiempo")

    def publish(self, creation_id: str) -> str:
        data = self._request("POST", f"{self.ig_user_id}/media_publish",
                             creation_id=creation_id)
        mid = data.get("id")
        if not mid:
            raise PermanentError(f"media_publish sin 'id': {data}")
        return str(mid)

    def publish_story(self, media_url: str, is_video: bool = False) -> str:
        """Ciclo completo: container -> ready -> publish. Devuelve media_id."""
        cid = self.create_story_container(media_url, is_video=is_video)
        self.wait_container_ready(cid, is_video=is_video)
        return self.publish(cid)


# --- tokens (refresco long-lived, sin app secret) ----------------------------
def refresh_long_lived_token(access_token: str, graph_version: str = "v23.0") -> dict[str, Any]:
    """GET /refresh_access_token?grant_type=ig_refresh_token. Devuelve nuevo token.

    Respuesta: {access_token, token_type, expires_in}. No requiere app secret.
    """
    register_secret(access_token)
    url = f"{GRAPH_HOST}/{graph_version}/refresh_access_token"
    resp = requests.get(url, params={"grant_type": "ig_refresh_token",
                                      "access_token": access_token}, timeout=60)
    if not resp.ok:
        raise AuthError(f"No se pudo refrescar el token: {resp.text[:200]}")
    data = resp.json()
    register_secret(data.get("access_token", ""))
    return data


def exchange_short_for_long(short_token: str, app_secret: str,
                            graph_version: str = "v23.0") -> dict[str, Any]:
    """Intercambio inicial short-lived -> long-lived (se hace UNA vez, manual)."""
    register_secret(short_token)
    register_secret(app_secret)
    url = f"{GRAPH_HOST}/{graph_version}/access_token"
    resp = requests.get(url, params={"grant_type": "ig_exchange_token",
                                      "client_secret": app_secret,
                                      "access_token": short_token}, timeout=60)
    if not resp.ok:
        raise AuthError(f"No se pudo intercambiar el token: {resp.text[:200]}")
    data = resp.json()
    register_secret(data.get("access_token", ""))
    return data
