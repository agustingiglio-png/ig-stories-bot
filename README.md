# ig-stories-bot

Publica automáticamente todos los días a las **13:00 hora de Argentina** un
conjunto fijo de fotos (~10) como **Instagram Stories**, usando **solo la API
oficial de Meta**. Costo **$0**. Sin navegador automatizado, sin scraping, sin
APIs no oficiales.

> Lo elegís una vez, lo dejás corriendo en la nube (GitHub Actions) y te olvidás.
> Si un día no querés publicar: `python manage.py skip today`.

---

## 0. Lo que tenés que saber ANTES de empezar (límites reales de la API oficial)

Verifiqué la documentación oficial de Meta el **2026-08-19**. Tres cosas de tu
idea original **no se pueden** hacer tal cual, por límites de la API (no hay
truco legal para saltearlos):

1. **Meta exige una URL pública por imagen.** La API descarga (`cURL`) cada foto
   de una URL accesible en internet. **No** se pueden subir archivos 100%
   locales. → Este proyecto expone cada foto **solo unos segundos**, bajo una URL
   aleatoria de un túnel efímero de Cloudflare, y la baja enseguida. Nunca quedan
   alojadas de forma permanente.
2. **Solo JPEG.** La API **no** publica PNG. Podés poner PNG en la carpeta: el
   sistema los convierte a JPG antes de publicar.
3. **Si la máquina está apagada, no publica.** Por eso este proyecto corre en la
   **nube gratuita de GitHub Actions** (siempre encendida), no en tu PC.

Todo lo demás de tu pedido está implementado.

---

## 1. Qué API se usa (documentación de referencia)

| Ítem | Valor |
|------|-------|
| Plataforma | **Instagram Platform — Content Publishing API** |
| Variante | **Instagram API with Instagram Login** (NO requiere página de Facebook) |
| Versión de Graph API | **v23.0** (configurable con `GRAPH_VERSION`) |
| Host | `https://graph.instagram.com` |
| Endpoints | `POST /<IG_ID>/media` (crea container) · `GET /<container_id>?fields=status_code` · `POST /<IG_ID>/media_publish` · `GET /<IG_ID>/content_publishing_limit` · `GET /refresh_access_token` |
| Parámetro clave de Stories | `media_type=STORIES` |
| Permisos (scopes) | `instagram_business_basic`, `instagram_business_content_publish` |
| Tipo de cuenta | Instagram **Professional** (Business o Creator) |
| Formato de imagen | **JPEG únicamente** |
| Límite de publicación | **hasta 100 posts / 24 h** (ventana móvil). Reels y Stories cuentan en el mismo cupo. 10/día = sin problema. |
| Token | Long-lived, dura **~60 días**, se refresca por API (sin app secret) |
| Fecha de verificación | **2026-08-19** |

**Restricciones de Stories** (según docs): no se pueden agregar stickers de
link/encuesta/ubicación vía API (sí mención de usuarios sin sticker). La Story
expira a las 24 h como cualquier historia normal.

Docs oficiales:
- Content Publishing: https://developers.facebook.com/docs/instagram-platform/content-publishing/
- Instagram API with Instagram Login: https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/
- Límite de publicación: `GET /<IG_ID>/content_publishing_limit`

---

## 2. Cómo funciona (arquitectura)

```
Tu PC (opcional, para gestionar)              GitHub (nube, GRATIS, siempre on)
┌───────────────────────────┐                ┌────────────────────────────────┐
│ python manage.py photos    │  git push      │ .github/workflows/publish.yml   │
│ python manage.py skip today│ ─────────────► │  cron 16:00 UTC = 13:00 ART     │
│ python manage.py status    │  git pull      │                                 │
└───────────────────────────┘ ◄───────────── │  1. lee skip / idempotencia     │
                                              │  2. valida las fotos (JPEG)     │
                                              │  3. túnel Cloudflare efímero    │
                                              │  4. publica c/ Story vía API    │
   photos/  01.jpg 02.jpg ...  (en el repo)   │  5. commitea el estado (SQLite) │
   state/app.sqlite  (estado + historial)     └────────────────────────────────┘
```

- **Estado / historial / skips**: SQLite (`state/app.sqlite`), commiteado de
  vuelta al repo en cada corrida (así `status`/`history` lo ven desde tu PC).
- **Idempotencia**: si un día ya está `COMPLETED`, no republica. Cada Story se
  marca publicada apenas se confirma → si algo se corta, al reintentar solo
  publica las que faltan (nunca duplica).
- **Zona horaria**: toda la lógica usa `America/Argentina/Buenos_Aires`
  explícitamente; nunca depende del reloj del servidor.

---

## 3. Instalación desde cero

### 3.1. Instalar Python 3
- Windows: descargá Python 3.12 de https://www.python.org/downloads/ y durante
  la instalación tildá **“Add Python to PATH”**.
- Verificá: `python --version` (debe decir 3.10 o superior).

### 3.2. Bajar este proyecto y crear el entorno virtual
```bash
cd ig-stories-bot
python -m venv .venv
```
Activarlo:
- Windows (PowerShell): `.\.venv\Scripts\Activate.ps1`
- Linux/macOS: `source .venv/bin/activate`

### 3.3. Instalar dependencias
```bash
pip install -r requirements.txt
```

### 3.4. Configurar `.env` (local)
```bash
cp .env.example .env
```
Editá `.env` y completá los valores (los sacás en el paso 5). **Nunca subas
`.env` a git** (ya está en `.gitignore`).

### 3.5. Configurar Meta (paso por paso, para principiantes)

> Objetivo: obtener `IG_ACCESS_TOKEN` (token de larga duración) y tu `IG_USER_ID`.

1. **Convertí tu cuenta de Instagram a Professional.**
   En la app de Instagram: *Configuración → Cuenta → Cambiar a cuenta
   profesional* → elegí **Empresa** o **Creador**. (Es gratis y reversible.)
2. **Creá una app de Meta.**
   Entrá a https://developers.facebook.com/apps/ → *Crear app* → tipo
   **“Empresa”/“Business”**. Ponele un nombre cualquiera.
3. **Agregá el producto “Instagram”.**
   En el panel de la app → *Agregar producto* → **Instagram** → usá la opción
   **“API con inicio de sesión de Instagram” (Instagram Login)**.
4. **Agregá tu cuenta como probador (Instagram Tester).**
   En *Instagram → Roles / API setup*, agregá tu propia cuenta de Instagram
   como **Instagram Tester** y aceptá la invitación desde la app de Instagram
   (*Configuración → Apps y sitios web → Invitaciones de tester*).
   Esto te permite publicar en **tu** cuenta **sin App Review**.
5. **Generá un token con los permisos correctos.**
   En la herramienta de tokens de la app, generá un token para tu cuenta con
   los scopes **`instagram_business_basic`** y
   **`instagram_business_content_publish`**. Esto te da un token de **corta
   duración**.
6. **Convertilo a larga duración** (dura ~60 días). Copiá tu **App Secret** al
   `.env` (`IG_APP_SECRET=`) y corré:
   ```bash
   python manage.py exchange-token EL_TOKEN_CORTO
   ```
   Copiá el token largo que imprime a `IG_ACCESS_TOKEN` en el `.env`.
7. **Dejá `IG_USER_ID` vacío**: el sistema lo resuelve solo la primera vez.
   (O corré `python manage.py check` y lo verás.)

> ¿Necesito **App Review**? Para publicar en **tu propia** cuenta agregada como
> Instagram Tester, **no**. App Review solo hace falta si algún día querés que la
> app publique en cuentas de **otras** personas.

### 3.6. Poner las fotos (y/o videos)
Copiá tus medios a la carpeta `photos/`, nombrados para que queden en orden:
```
photos/01.jpg  photos/02.mp4  photos/03.png  ...  photos/10.jpg
```
Se aceptan **imágenes** (`.jpg`/`.png`) y **videos** (`.mp4`/`.mov`), mezclados.
Todos se publican como **Historias** (nunca como post del feed).
O usá el comando (los copia y numera solos):
```bash
python manage.py photos add C:\ruta\foto_a.jpg C:\ruta\video_b.mp4
```
Recomendado para Stories: verticales **1080×1920** (9:16). El sistema avisa si
algo no es vertical y convierte PNG→JPG automáticamente.

Límites de **video** (Stories por API): MP4/MOV, vertical 9:16, **≤60 s**, ≤100 MB.
Para que el sistema verifique la duración localmente necesitás `ffmpeg`/`ffprobe`
instalado (opcional; en GitHub Actions ya viene). Sin él, no valida la duración y
Meta rechazará el video si supera 60 s.

### 3.7. Probar la conexión con Meta
```bash
python manage.py check
```
Debe imprimir tu `@usuario`, el tipo de cuenta y el cupo de publicación.

### 3.8. Dry-run (simula todo, no publica nada)
```bash
python manage.py dry-run
```
Verifica: config, credenciales, hora/zona, skip del día, imágenes, permisos,
conexión con Meta y que `cloudflared` esté disponible.

### 3.9. Probar una publicación manual
> ⚠ Esto **sí publica de verdad** en tu Instagram.
Necesitás `cloudflared` instalado localmente para esta prueba
(ver *Instalar cloudflared* abajo). Después:
```bash
python manage.py publish
```
Es idempotente: si lo corrés dos veces el mismo día, la segunda no republica.

### 3.10. Configurar el scheduler (la nube, GitHub Actions)

1. Creá un repositorio **privado** en GitHub y subí este proyecto:
   ```bash
   git init
   git add .
   git commit -m "init ig-stories-bot"
   git branch -M main
   git remote add origin git@github.com:TU_USUARIO/ig-stories-bot.git
   git push -u origin main
   ```
   > `photos/` y `state/` **sí** se suben (son el contenido y el estado).
   > `.env` **no** se sube.
2. En GitHub → *Settings → Secrets and variables → Actions → New repository
   secret*, cargá:
   - `IG_ACCESS_TOKEN` = tu token largo
   - `IG_USER_ID` = tu user id (opcional; podés dejarlo y lo cachea solo)
   - (opcional) `GH_PAT` = un Personal Access Token con permiso de **secrets**
     (para el refresco automático del token; ver paso 5 de mantenimiento).
   - (opcional, como *Variable*) `GRAPH_VERSION` = `v23.0`
3. Listo. El workflow `publish-stories` corre solo a las **16:00 UTC = 13:00
   ART** todos los días.

`cloudflared` en la nube se instala solo (lo hace el workflow). No tenés que
hacer nada.

### 3.11. Comprobar que el scheduler quedó bien
- En GitHub → pestaña **Actions** → deberías ver el workflow `publish-stories`.
- Probalo a mano: entrá al workflow → **Run workflow** (botón *workflow_dispatch*).
- Mirá el log del run; y después `python manage.py history` en tu PC
  (hace `git pull` y te muestra el resultado).

### 3.12. Configurar un skip
```bash
python manage.py skip today          # no publica hoy
python manage.py unskip today        # lo vuelve a habilitar
python manage.py skip 2026-08-25     # no publica esa fecha
python manage.py unskip 2026-08-25
```
Estos comandos hacen `git push` solos para que la nube los vea. Hacelo **antes**
de las 13:00 ART.

### 3.13. Comprobar logs e historial
```bash
python manage.py status      # estado de hoy
python manage.py history     # últimas corridas (fecha, estado, detalle)
```
Los logs detallados de cada día quedan en `logs/AAAA-MM-DD.log` (y se commitean
desde la nube).

---

## 4. Instalar `cloudflared` (solo para pruebas locales)

- **Windows**: `winget install --id Cloudflare.cloudflared`
  (o bajá el `.exe` de https://github.com/cloudflare/cloudflared/releases y
  poné su ruta en `CLOUDFLARED_BIN` del `.env`).
- **macOS**: `brew install cloudflared`
- **Linux**: descargá el binario `cloudflared-linux-amd64` de las releases.

No hace falta cuenta de Cloudflare ni tarjeta: se usa el túnel efímero
`trycloudflare` (gratuito).

---

## 5. Mantenimiento del token (para que nunca expire)

El token dura ~60 días. Dos opciones:

- **Automático (recomendado):** cargá el secret `GH_PAT` (un Personal Access
  Token con permiso de *secrets*). El workflow `refresh-token` corre cada lunes,
  refresca el token y reescribe el secret `IG_ACCESS_TOKEN` solo. Cómo crear el
  PAT: GitHub → *Settings → Developer settings → Fine-grained tokens* → dale
  acceso a este repo con permiso **Secrets: Read and write**.
- **Manual:** cada ~50 días corré `python manage.py refresh-token --force` y
  actualizá el secret `IG_ACCESS_TOKEN` con el valor `NUEVO_TOKEN=` que imprime.

> Este es el **único** punto que no es 100% "para siempre" sin el PAT. Con el
> PAT, es totalmente desatendido.

---

## 6. Comandos (referencia rápida)

```bash
python manage.py status                    # estado del día
python manage.py photos                    # listar y validar fotos
python manage.py photos add a.jpg b.png    # agregar fotos
python manage.py photos clear              # borrar todas
python manage.py skip today                # no publicar hoy
python manage.py unskip today              # rehabilitar hoy
python manage.py skip 2026-08-25           # skip de una fecha
python manage.py unskip 2026-08-25
python manage.py dry-run                   # simula, no publica
python manage.py publish                   # publica el día (idempotente)
python manage.py history                   # historial
python manage.py check                     # prueba conexión con Meta
python manage.py exchange-token TOKEN      # short-lived -> long-lived (1 vez)
python manage.py refresh-token [--force]   # refresca el token
```

---

## 7. Seguridad

- Los secretos **nunca** están en el código: van en `.env` (local, ignorado por
  git) o en **GitHub Secrets** (nube, cifrados).
- Los logs **jamás** imprimen tokens completos (hay un filtro que los censura).
- Las fotos solo se exponen a internet unos segundos, bajo una URL aleatoria, y
  el repo es **privado**.
- Recomendación: usá el token de larga duración (no el App Secret) en el día a
  día; el App Secret solo se necesita una vez para el intercambio inicial.

---

## 8. Robustez: qué pasa si…

| Situación | Qué hace el sistema |
|-----------|---------------------|
| Se corta internet / error de red | Reintenta con backoff; si persiste, marca la Story como fallida y sigue con las demás. |
| Meta devuelve **429** (rate limit) | Reintenta con backoff largo (60/180/300 s). |
| Error temporal (5xx) | Reintenta (5/15/45 s). |
| La máquina/nube se reinicia a mitad | El estado quedó guardado por Story; al reejecutar `publish` reanuda solo lo que falta. |
| Se ejecuta dos veces el mismo día | El segundo run ve `COMPLETED` y **no** republica. |
| Una imagen no cumple requisitos | Falla **antes** de empezar la secuencia (no publica nada a medias). |
| El token expiró | `AuthError`: no reintenta, corta y registra el error (arreglás el token y reejecutás). |
| Meta rechaza una imagen puntual | Marca esa Story como fallida y sigue con el resto. |

---

## 9. Tests

```bash
pip install pytest
python -m pytest -q
```
Cubren: skip de hoy/fecha futura, unskip, doble ejecución, idempotencia,
publicación parcial + reanudación, imágenes faltantes/inválidas, PNG→JPEG, error
de autenticación, rate limit, error temporal, clasificación de errores y
timezone Argentina.

---

## 10. Detalles técnicos

- Python 3.10+ · SQLite (módulo estándar `sqlite3`) · Pillow · requests.
- `zoneinfo` con el paquete `tzdata` (necesario en Windows).
- Sin Docker (no aporta ventaja acá). Sin servidor pago. Sin Selenium/Playwright.
