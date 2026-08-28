#!/usr/bin/env python3
"""ig-stories-bot · CLI de gestion.

Comandos:
  python manage.py status                 estado del dia (habilitado/omitido, fotos, proxima...)
  python manage.py photos                 lista y valida las fotos de photos/
  python manage.py photos add a.jpg b.png agrega fotos (las copia y ordena)
  python manage.py photos clear           borra todas las fotos
  python manage.py skip today             no publicar hoy
  python manage.py unskip today           volver a habilitar hoy
  python manage.py skip 2026-08-25        no publicar esa fecha
  python manage.py unskip 2026-08-25      habilitar esa fecha
  python manage.py dry-run                simula todo, sin publicar
  python manage.py publish                publica lo del dia (idempotente)
  python manage.py history                ultimas corridas
  python manage.py check                  prueba credenciales/conexion con Meta
  python manage.py exchange-token TOKEN   short-lived -> long-lived (una vez)
  python manage.py refresh-token [--force] refresca el token long-lived

Los comandos que cambian estado (skip/unskip/photos) intentan git commit+push
automaticamente para que la corrida en la nube (GitHub Actions) los vea.
Desactivalo con --no-push. status/history hacen git pull (desactivar: --no-pull).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from igstories import db
from igstories.config import (PHOTOS_DIR, ROOT, TZ, get_settings, mask,
                              next_publish_dt, now_ar, today_ar)
from igstories.logging_setup import setup_logging


# --- helpers -----------------------------------------------------------------
def _parse_day(token: str) -> str:
    token = token.strip().lower()
    if token in ("today", "hoy"):
        return today_ar().isoformat()
    if token in ("tomorrow", "manana", "mañana"):
        from datetime import timedelta
        return (today_ar() + timedelta(days=1)).isoformat()
    try:
        return date.fromisoformat(token).isoformat()
    except ValueError:
        sys.exit(f"Fecha invalida: '{token}'. Usá 'today' o 'YYYY-MM-DD'.")


def _git(*args: str) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).strip()
    except FileNotFoundError:
        return 127, "git no instalado"


def _is_git_repo() -> bool:
    return _git("rev-parse", "--is-inside-work-tree")[0] == 0


def _git_push(message: str) -> None:
    if not _is_git_repo():
        print("  (no es repo git; guardado solo localmente)")
        return
    _git("add", "state", "photos")
    code, _ = _git("commit", "-m", message)
    if code != 0:
        print("  (nada nuevo para commitear)")
        return
    code, out = _git("push")
    print("  push OK" if code == 0 else f"  push fallo (commit local hecho): {out.splitlines()[-1:]}")


def _git_pull() -> None:
    if _is_git_repo():
        _git("pull", "--rebase", "--autostash")


# --- comandos ----------------------------------------------------------------
def cmd_status(args):
    if not args.no_pull:
        _git_pull()
    db.init_db()
    day = today_ar().isoformat()
    photos = _count_valid_photos()
    skipped = db.is_skipped(day)
    run = db.get_run(day)

    print(f"Fecha: {day}")
    print(f"Hora programada: 13:00 America/Argentina/Buenos_Aires")
    print(f"Ahora (ART): {now_ar().strftime('%Y-%m-%d %H:%M:%S')}")
    if skipped:
        print("Estado: OMITIDO")
        print("Motivo: skip configurado para hoy")
    elif run and run["status"] == "COMPLETED":
        print("Estado: PUBLICADO HOY")
    else:
        print("Estado: HABILITADO")
    print(f"Fotos configuradas: {photos}")

    last = _last_completed()
    print(f"Ultima publicacion: {last or '(ninguna)'}")
    print(f"Proxima publicacion: {next_publish_dt().strftime('%Y-%m-%d %H:%M')} ART")
    print(f"Skip de hoy: {'SI' if skipped else 'NO'}")
    upcoming = [d for d in db.list_skips() if d > day]
    if upcoming:
        print(f"Skips futuros: {', '.join(upcoming)}")


def cmd_photos(args):
    from igstories.images import ImageError, build_photos, discover
    if args.action == "clear":
        for p in discover():
            p.unlink()
        print("Fotos borradas.")
        if not args.no_push:
            _git_push("photos: clear")
        return
    if args.action == "add":
        PHOTOS_DIR.mkdir(parents=True, exist_ok=True)
        existing = len(discover())
        for i, src in enumerate(args.paths, start=existing + 1):
            srcp = Path(src)
            if not srcp.exists():
                print(f"  no existe: {src}")
                continue
            ext = srcp.suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".mp4", ".mov"):
                print(f"  formato no soportado (usa jpg/png/mp4/mov): {src}")
                continue
            dst = PHOTOS_DIR / f"{i:02d}{ext}"
            shutil.copy2(srcp, dst)
            print(f"  + {dst.name}  <-  {srcp.name}")
        if not args.no_push:
            _git_push("photos: add")
        # y mostrar el listado validado
    # listar
    print(f"Carpeta: {PHOTOS_DIR}")
    files = discover()
    if not files:
        print("  (vacia) Poné tus imagenes .jpg/.png aca, ordenadas 01, 02, ...")
        return
    try:
        photos = build_photos()
        for p in photos:
            warn = ("  ⚠ " + "; ".join(p.warnings)) if p.warnings else ""
            if p.is_video:
                print(f"  {p.seq:02d}  {p.filename:20s} [VIDEO]{warn}")
            else:
                flag = "  [PNG->JPEG]" if p.is_png else ""
                print(f"  {p.seq:02d}  {p.filename:20s} {p.width}x{p.height}{flag}{warn}")
        print(f"Total valido: {len(photos)}")
    except ImageError as e:
        print(f"  ⚠ Config invalida: {e}")


def cmd_skip(args):
    day = _parse_day(args.day)
    db.init_db()
    db.add_skip(day)
    print(f"OK. NO se publicara el {day}.")
    if not args.no_push:
        _git_push(f"skip: {day}")


def cmd_unskip(args):
    day = _parse_day(args.day)
    db.init_db()
    removed = db.remove_skip(day)
    print(f"OK. Se habilito la publicacion del {day}." if removed
          else f"El {day} no tenia skip.")
    if not args.no_push:
        _git_push(f"unskip: {day}")


def cmd_dry_run(args):
    from igstories import publisher
    setup_logging(verbose=True)
    res = publisher.dry_run(get_settings())
    sys.exit(0 if res.status == "OK" else 1)


def cmd_publish(args):
    from igstories import publisher
    day = today_ar().isoformat()
    setup_logging(run_date=day, verbose=True)
    res = publisher.publish(get_settings())
    if not args.no_push:
        _git_push(f"run: {day} -> {res.status} ({res.published}/{res.total})")
    sys.exit(0 if res.status in ("COMPLETED", "SKIPPED") else 1)


def cmd_history(args):
    if not args.no_pull:
        _git_pull()
    db.init_db()
    rows = db.history(args.limit)
    if not rows:
        print("Sin historial todavia.")
        return
    print(f"{'FECHA':12} {'ESTADO':10} {'INICIO':20} {'FIN':20} DETALLE")
    for r in rows:
        detail = r["reason"] or r["error"] or ""
        print(f"{r['date']:12} {r['status']:10} {str(r['started_at'] or ''):20} "
              f"{str(r['finished_at'] or ''):20} {detail}")


def cmd_check(args):
    from igstories.instagram import ApiError, AuthError
    from igstories import publisher
    setup_logging(verbose=True)
    db.init_db()
    s = get_settings()
    print(f"Token: {mask(s.access_token)}   GRAPH_VERSION={s.graph_version}")
    if not s.has_token:
        sys.exit("Falta IG_ACCESS_TOKEN.")
    try:
        client = publisher._client(s)
        acc = client.get_account()
        print(f"Conexion OK -> @{acc.get('username')} ({acc.get('account_type')}) "
              f"user_id={client.ig_user_id}")
        lim = client.content_publishing_limit()
        print(f"Cuota 24h: {(lim.get('data') or [{}])[0].get('quota_usage','?')}")
    except (ApiError, AuthError) as e:
        sys.exit(f"Fallo: {e}")


def cmd_exchange_token(args):
    from igstories.instagram import exchange_short_for_long
    s = get_settings()
    if not s.app_secret:
        sys.exit("Falta IG_APP_SECRET en .env para el intercambio.")
    data = exchange_short_for_long(args.short_token, s.app_secret, s.graph_version)
    tok = data.get("access_token", "")
    print("Long-lived token obtenido. Pegalo en IG_ACCESS_TOKEN (.env o Secret):")
    print(tok)
    print(f"(expira en ~{int(data.get('expires_in',0))//86400} dias)")


def _update_env_token(token: str) -> bool:
    """Reescribe IG_ACCESS_TOKEN en el .env local (para el camino-PC)."""
    env = ROOT / ".env"
    if not env.exists() or not token:
        return False
    lines = env.read_text(encoding="utf-8").splitlines()
    out, found = [], False
    for ln in lines:
        if ln.startswith("IG_ACCESS_TOKEN="):
            out.append(f"IG_ACCESS_TOKEN={token}")
            found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"IG_ACCESS_TOKEN={token}")
    env.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True


def cmd_refresh_token(args):
    from igstories import publisher
    setup_logging(verbose=True)
    data = publisher.refresh_token_if_needed(get_settings(), force=args.force)
    if data is None:
        print("No hacia falta refrescar.")
        return
    tok = data.get("access_token", "")
    if getattr(args, "write_env", False):
        if _update_env_token(tok):
            print("Token actualizado en .env")
    else:
        print("NUEVO_TOKEN=" + tok)  # el workflow captura esta linea para actualizar el Secret


# --- utilidades de status ----------------------------------------------------
def _count_valid_photos() -> int:
    from igstories.images import build_photos, ImageError
    try:
        return len(build_photos())
    except ImageError:
        from igstories.images import discover
        return len(discover())


def _last_completed() -> str | None:
    for r in db.history(60):
        if r["status"] == "COMPLETED":
            return f"{r['date']} ({r['finished_at']})"
    return None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="manage.py", description="Gestion de ig-stories-bot")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("status", help="estado del dia")
    sp.add_argument("--no-pull", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("photos", help="listar/agregar/borrar fotos")
    sp.add_argument("action", nargs="?", choices=["list", "add", "clear"], default="list")
    sp.add_argument("paths", nargs="*", help="archivos a agregar (action=add)")
    sp.add_argument("--no-push", action="store_true")
    sp.set_defaults(func=cmd_photos)

    sp = sub.add_parser("skip", help="no publicar un dia")
    sp.add_argument("day")
    sp.add_argument("--no-push", action="store_true")
    sp.set_defaults(func=cmd_skip)

    sp = sub.add_parser("unskip", help="habilitar un dia")
    sp.add_argument("day")
    sp.add_argument("--no-push", action="store_true")
    sp.set_defaults(func=cmd_unskip)

    sp = sub.add_parser("dry-run", help="simular sin publicar")
    sp.set_defaults(func=cmd_dry_run)

    sp = sub.add_parser("publish", help="publicar el dia (idempotente)")
    sp.add_argument("--no-push", action="store_true")
    sp.set_defaults(func=cmd_publish)

    sp = sub.add_parser("history", help="historial de corridas")
    sp.add_argument("--limit", type=int, default=30)
    sp.add_argument("--no-pull", action="store_true")
    sp.set_defaults(func=cmd_history)

    sp = sub.add_parser("check", help="probar conexion con Meta")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("exchange-token", help="short-lived -> long-lived (una vez)")
    sp.add_argument("short_token")
    sp.set_defaults(func=cmd_exchange_token)

    sp = sub.add_parser("refresh-token", help="refrescar token long-lived")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--write-env", action="store_true",
                    help="escribe el token nuevo en .env (camino-PC)")
    sp.set_defaults(func=cmd_refresh_token)
    return p


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
