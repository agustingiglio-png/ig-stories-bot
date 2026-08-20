"""Exposicion EFIMERA de las fotos mediante Cloudflare Tunnel (gratis).

Meta EXIGE que cada imagen este en una URL publica al momento de publicar
("we cURL media... must be hosted on a publicly accessible server").

Estrategia para minimizar exposicion:
  1. Servimos las fotos con un http.server local en un directorio temporal.
  2. Los nombres de archivo son UUID aleatorios (no adivinables).
  3. Levantamos un tunel efimero de Cloudflare (trycloudflare, sin cuenta ni
     tarjeta) que da una URL https publica random.
  4. Publicamos las Stories (Meta descarga cada imagen en segundos).
  5. Cerramos el tunel y el server, y borramos los archivos.

Resultado: las fotos existen en internet solo durante la ventana de publicacion
(~segundos), bajo una URL aleatoria. Nunca quedan alojadas de forma permanente.
"""
from __future__ import annotations

import http.server
import re
import shutil
import socketserver
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .logging_setup import get_logger

_URL_RE = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    # Aseguramos el content-type correcto para que Meta descargue bien el media.
    extensions_map = {
        **http.server.SimpleHTTPRequestHandler.extensions_map,
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
    }

    def log_message(self, *_a):  # silencio: no ensuciar stdout
        pass


class _Server:
    def __init__(self, directory: Path):
        self.directory = str(directory)
        handler = lambda *a, **k: _QuietHandler(*a, directory=self.directory, **k)  # noqa: E731
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        except Exception:
            pass


class HostingError(Exception):
    """Error transitorio al montar el tunel (se puede reintentar)."""


def _find_cloudflared(explicit: str = "") -> str:
    if explicit:
        return explicit
    found = shutil.which("cloudflared")
    if not found:
        raise HostingError(
            "No se encontro 'cloudflared'. Instalalo (ver README) o seteá CLOUDFLARED_BIN."
        )
    return found


@contextmanager
def public_urls(serve_dir: Path, filenames: list[str], cloudflared_bin: str = "",
                timeout: int = 45) -> Iterator[dict[str, str]]:
    """Context manager: entrega {filename: url_publica} mientras el bloque corre.

    Al salir del bloque cierra tunel + server (las URLs dejan de existir).
    """
    log = get_logger()
    bin_path = _find_cloudflared(cloudflared_bin)

    server = _Server(serve_dir)
    server.start()
    log.info("Servidor local efimero en 127.0.0.1:%d", server.port)

    proc = subprocess.Popen(
        [bin_path, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{server.port}"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
    )

    base_url = None
    deadline = time.time() + timeout
    try:
        assert proc.stdout is not None
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    raise HostingError("cloudflared termino antes de dar una URL")
                continue
            m = _URL_RE.search(line)
            if m:
                base_url = m.group(0)
                break
        if not base_url:
            raise HostingError("Timeout esperando la URL del tunel de Cloudflare")

        log.info("Tunel efimero activo (URL random de trycloudflare)")
        # Drenar el resto de la salida de cloudflared para que no bloquee.
        threading.Thread(target=lambda: [proc.stdout.readline() for _ in iter(int, 1)],
                         daemon=True).start()

        yield {fn: f"{base_url}/{fn}" for fn in filenames}
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        server.stop()
        log.info("Tunel y servidor efimeros cerrados (las URLs ya no existen)")
