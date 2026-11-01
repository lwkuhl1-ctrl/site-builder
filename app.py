"""Site Builder: app for making SEO/AEO websites for local businesses.

On your PC:   python app.py   (or double-click "Start Site Builder.bat"), opens http://localhost:8840
On Render:    see render.yaml. Render sets PORT; DATA_DIR points at the persistent disk;
              BUILDER_PASSWORD locks the whole app behind a login.

Built sites preview at /preview/<slug>/ on the same address. Client inputs are
saved in <data>/clients/<slug>/, built sites in <data>/sites/<slug>/.
"""
from __future__ import annotations

import base64
import hmac
import json
import mimetypes
import os
import re
import sys
import traceback
import webbrowser
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from sitebuilder import stock, writer  # noqa: E402
from sitebuilder.generator import build_site, slugify  # noqa: E402

ON_SERVER = bool(os.environ.get("PORT"))          # Render (or any host) sets PORT
DATA = Path(os.environ.get("DATA_DIR") or ROOT)
CLIENTS, SITES = DATA / "clients", DATA / "sites"
PORT = int(os.environ.get("PORT") or 8840)        # 8765 is Jarvis's local port

KEY_NAMES = ("ANTHROPIC_API_KEY", "PIXABAY_API_KEY", "PEXELS_API_KEY")


def load_env():
    """API keys from Windows user settings (Set Up Keys.bat), then a .env next to this script.
    On Render they come from the service's environment instead.

    Reads the registry directly so keys saved after this program (or the app
    that launched it) started still count."""
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                for name in KEY_NAMES:
                    try:
                        value = winreg.QueryValueEx(k, name)[0]
                    except FileNotFoundError:
                        continue
                    if value and not os.environ.get(name):  # a blank inherited value doesn't count
                        os.environ[name] = value
        except OSError:
            pass
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() and v.strip() and not k.strip().startswith("#") and not os.environ.get(k.strip()):
                os.environ[k.strip()] = v.strip().strip('"')


def save_data_url(data_url: str | None, dst: Path) -> Path | None:
    if not data_url:
        return dst if dst.exists() else None
    if data_url == "remove":
        dst.unlink(missing_ok=True)
        return None
    _, b64 = data_url.split(",", 1)
    dst.write_bytes(base64.b64decode(b64))
    return dst


def export_zip() -> bytes:
    """clients/ and sites/ (not the stock cache, which refills itself) as one zip."""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for top in (CLIENTS, SITES):
            for f in top.rglob("*"):
                if f.is_file():
                    z.write(f, f.relative_to(DATA).as_posix())
    return buf.getvalue()


def import_zip(data: bytes) -> list[str]:
    """Unpack an export into clients/ and sites/, replacing those businesses. Returns their slugs."""
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
        for n in names:  # only clients/<slug>/... and sites/<slug>/..., nothing outside the data folder
            parts = n.split("/")
            if parts[0] not in ("clients", "sites") or len(parts) < 3 or ".." in parts or not re.fullmatch(r"[a-z0-9-]+", parts[1]):
                raise ValueError(f"Unexpected file in backup: {n}")
        slugs = sorted({n.split("/")[1] for n in names})
        for n in names:
            dst = DATA / n
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(z.read(n))
    return slugs


_LINK = re.compile(r'((?:href|src|action|content)=")/(?!/)')
_SRCSET = re.compile(r'srcset="([^"]*)"')


def prefix_links(html: str, base: str) -> str:
    """Point a built site's root links (/services/, /assets/...) at /preview/<slug>/ so it
    can be clicked around under the builder's own address."""
    html = _LINK.sub(lambda m: m[1] + base, html)
    html = _SRCSET.sub(lambda m: 'srcset="' + re.sub(r"(^|,\s*)/(?!/)", lambda n: n[1] + base, m[1]) + '"', html)
    return html.replace("url(/assets/", f"url({base}assets/")


class Builder(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # Login ----------------------------------------------------------------
    def authorized(self) -> bool:
        pw = os.environ.get("BUILDER_PASSWORD", "")
        if not pw:
            return not ON_SERVER  # never run open on the internet
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Basic "):
            try:
                given = base64.b64decode(auth[6:]).decode("utf-8").split(":", 1)[-1]
            except Exception:
                given = ""
            if hmac.compare_digest(given.encode(), pw.encode()):
                return True
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Site Builder", charset="UTF-8"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Site Builder: log in with any username and your BUILDER_PASSWORD."
                         if pw else b"Set BUILDER_PASSWORD on the server to turn the builder on.")
        return False

    # Responses ------------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_bytes(self, data: bytes, ctype: str, code=200, download: str | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if download:
            self.send_header("Content-Disposition", f'attachment; filename="{download}"')
        self.end_headers()
        self.wfile.write(data)

    def send_file(self, path: Path, download: str | None = None):
        if not path.is_file():
            self.send_error(404)
            return
        self.send_bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream", download=download)

    def preview(self, slug: str, rest: str):
        """Serve sites/<slug>/site with Cloudflare-style clean URLs under /preview/<slug>/."""
        root = (SITES / slug / "site").resolve()
        p = (root / unquote(rest)).resolve()
        if root not in p.parents and p != root:
            return self.send_error(404)
        if p.is_dir():
            p = p / "index.html"
        code = 200
        if not p.is_file():
            p, code = root / "404.html", 404
            if not p.is_file():
                return self.send_error(404, "Build this site first")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        data = p.read_bytes()
        if p.suffix == ".html":
            data = prefix_links(data.decode("utf-8"), f"/preview/{slug}/").encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_bytes(data, ctype, code)

    # Routes ---------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/healthz":
            return self.send_bytes(b"ok", "text/plain")
        if not self.authorized():
            return
        q = parse_qs(u.query)
        if u.path == "/":
            return self.send_file(ROOT / "ui.html")
        if u.path == "/api/clients":
            rows = []
            for f in sorted(CLIENTS.glob("*/input.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                rows.append({"slug": f.parent.name, "name": json.loads(f.read_text(encoding="utf-8")).get("name", f.parent.name),
                             "updated": datetime.fromtimestamp(f.stat().st_mtime).strftime("%b %d, %I:%M %p")})
            return self.send_json({"clients": rows, "ai": writer.ai_available(), "stock": stock.available(),
                                   "server": ON_SERVER})
        if u.path == "/api/client":
            slug = slugify(q.get("slug", [""])[0])
            f = CLIENTS / slug / "input.json"
            if not f.exists():
                return self.send_json({"error": "not found"}, 404)
            data = json.loads(f.read_text(encoding="utf-8"))
            for k, fn in (("logo", "logo.png"), ("hero", "hero.jpg"), ("about", "about.jpg"), ("before", "before.jpg"), ("after", "after.jpg")):
                data[f"_{k}_url"] = f"/client-file/{slug}/{fn}" if (CLIENTS / slug / fn).exists() else ""
            data["_built"] = (SITES / slug / "site" / "index.html").exists()
            pdir = CLIENTS / slug / "photos"
            data["_svc_photos"] = {f.stem[4:]: f"/client-file/{slug}/photos/{f.name}" for f in pdir.glob("svc-*.img")}
            data["_gallery"] = [{"file": f.name, "url": f"/client-file/{slug}/photos/{f.name}"}
                                for f in sorted(pdir.glob("gal-*.img"))]
            credits = SITES / slug / "photo-credits.json"
            data["_stock"] = [c["service"] for c in json.loads(credits.read_text())] if credits.exists() else []
            return self.send_json(data)
        m = re.fullmatch(r"/client-file/([a-z0-9-]+)/(logo\.png|(?:hero|about|before|after)\.jpg|photos/(?:svc|gal)-[a-z0-9-]+\.img)", u.path)
        if m:
            return self.send_file(CLIENTS / m[1] / m[2])
        if u.path == "/api/export":  # backup: every client and built site in one zip
            return self.send_bytes(export_zip(), "application/zip",
                                   download=f"site-builder-backup-{datetime.now():%Y-%m-%d}.zip")
        m = re.fullmatch(r"/download/([a-z0-9-]+)", u.path)
        if m:
            return self.send_file(SITES / m[1] / f"{m[1]}-site.zip", download=f"{m[1]}-site.zip")
        m = re.fullmatch(r"/preview/([a-z0-9-]+)(/.*)?", u.path)
        if m:
            if not m[2]:  # /preview/bonsai -> /preview/bonsai/
                self.send_response(301)
                self.send_header("Location", f"/preview/{m[1]}/")
                self.end_headers()
                return
            return self.preview(m[1], m[2].lstrip("/"))
        self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > 300_000_000:  # 300 MB: far above any real build or backup
            return self.send_error(413)
        raw = self.rfile.read(length)  # read before answering, so a wrong password gets a clean 401
        if not self.authorized():
            return
        u = urlparse(self.path)
        if u.path == "/api/import":  # zip from export_zip() / "Copy to Render.bat"
            try:
                return self.send_json({"ok": True, "imported": import_zip(raw)})
            except Exception as ex:
                return self.send_json({"ok": False, "error": str(ex)}, 400)
        body = json.loads(raw or b"{}")
        if u.path == "/api/build":
            return self.build(body)
        if u.path == "/api/open-folder":
            folder = SITES / slugify(body.get("slug", ""))
            if folder.exists() and not ON_SERVER and sys.platform == "win32":
                os.startfile(folder)  # noqa: S606 (local Windows app)
            return self.send_json({"ok": True})
        self.send_error(404)

    def build(self, body: dict):
        data = body.get("data") or {}
        lines = []
        try:
            if not data.get("name") or not data.get("city") or not data.get("state"):
                raise ValueError("Business name, city and state are required.")
            slug = slugify(data["name"])
            data["slug"] = slug
            cdir = CLIENTS / slug
            cdir.mkdir(parents=True, exist_ok=True)
            logo = save_data_url(body.get("logo"), cdir / "logo.png")
            hero = save_data_url(body.get("hero"), cdir / "hero.jpg")
            extra = {k: save_data_url(body.get(k), cdir / f"{k}.jpg") for k in ("about", "before", "after")}
            pdir = cdir / "photos"
            pdir.mkdir(exist_ok=True)
            for svc_slug, url in (body.get("svc_photos") or {}).items():
                save_data_url(url, pdir / f"svc-{slugify(svc_slug)}.img")
            for name in body.get("gallery_remove") or []:
                if re.fullmatch(r"gal-[a-z0-9-]+\.img", name):
                    (pdir / name).unlink(missing_ok=True)
            stamp = datetime.now().strftime("%Y%m%d%H%M%S")
            for n, url in enumerate(body.get("gallery_add") or []):
                save_data_url(url, pdir / f"gal-{stamp}-{n:02d}.img")
            (cdir / "input.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            res = build_site(data, SITES / slug, logo=logo, hero=hero,
                             svc_photos={f.stem[4:]: f for f in pdir.glob("svc-*.img")},
                             gallery=sorted(pdir.glob("gal-*.img")),
                             use_ai=bool(body.get("use_ai")), rewrite_copy=bool(body.get("rewrite_copy")), log=lines.append, **extra)
            return self.send_json({"ok": True, "slug": slug, "log": lines, "folder": str(SITES / slug),
                                   "pages": res["pages"], "stock": res["stock"], "no_photo": res["no_photo"]})
        except Exception as ex:  # show the problem in the UI instead of a dead request
            lines.append(traceback.format_exc())
            return self.send_json({"ok": False, "error": str(ex), "log": lines}, 400)


class OwnPortServer(ThreadingHTTPServer):
    """Refuses a port another copy already holds. Windows' default lets two servers
    share it silently, so a second launch would start a duplicate instead of noticing."""
    allow_reuse_address = False

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    load_env()
    CLIENTS.mkdir(parents=True, exist_ok=True)
    SITES.mkdir(parents=True, exist_ok=True)
    host = "0.0.0.0" if ON_SERVER else "127.0.0.1"
    try:
        srv = OwnPortServer((host, PORT), Builder)
    except OSError:  # already running (another window, or Claude's preview): just open it
        print(f"Site Builder is already running. Opening http://localhost:{PORT}/")
        webbrowser.open(f"http://localhost:{PORT}/")
        return
    url = f"http://localhost:{PORT}/"
    print(f"Site Builder running at {url}" + ("  (server mode, data in " + str(DATA) + ")" if ON_SERVER else ""))
    print("Login:", "password required" if os.environ.get("BUILDER_PASSWORD") else
          ("BLOCKED until BUILDER_PASSWORD is set" if ON_SERVER else "none (local only)"))
    print("AI copy:", "ON" if writer.ai_available() else "off (see README)")
    print("Stock photos:", "ON" if stock.available() else "off (see README)")
    if not ON_SERVER and "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
