"""Gestor de Correus - aplicació d'escriptori per netejar i organitzar comptes IMAP.

Executa:  python app.py
Si hi ha pywebview instal·lat s'obre en una finestra pròpia; si no, al navegador.
"""
import base64
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import migration
from imap_client import MailError, MailSession, test_smtp

APP_NAME = "Gestor de Correus"
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
FROZEN = getattr(sys, "frozen", False)


def log(*a):
    if sys.stdout:  # a l'.exe sense consola no hi ha stdout
        print(*a, flush=True)


# ------------------------------------------------------------- configuració
def config_dir():
    d = os.environ.get("GESTOR_CORREUS_HOME")
    if not d and FROZEN:
        # Versió portable: les dades viatgen amb l'.exe (p. ex. en un USB).
        cand = os.path.join(os.path.dirname(sys.executable), "GestorCorreus_dades")
        try:
            os.makedirs(cand, exist_ok=True)
            test = os.path.join(cand, ".w")
            open(test, "w").close()
            os.remove(test)
            d = cand
        except OSError:
            d = None
    if not d:
        if os.name == "nt":
            d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "GestorCorreus")
        else:
            d = os.path.join(os.path.expanduser("~"), ".config", "gestor-correus")
    os.makedirs(d, exist_ok=True)
    return d


CONFIG = os.path.join(config_dir(), "comptes.json")


def exports_dir():
    d = os.path.join(config_dir(), "Exportacions")
    os.makedirs(d, exist_ok=True)
    return d


def uploads_dir():
    d = os.path.join(config_dir(), "tmp")
    os.makedirs(d, exist_ok=True)
    return d


def clean_uploads():
    for f in os.listdir(uploads_dir()):
        try:
            os.remove(os.path.join(uploads_dir(), f))
        except OSError:
            pass


def safe_name(s):
    import re as _re
    return _re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", s).strip(" ._")[:60] or "correu"


def open_path(path, select=False):
    try:
        if os.name == "nt":
            if select:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R" if select else "", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) if select else path])
    except Exception as e:  # noqa
        raise MailError(f"No s'ha pogut obrir la carpeta: {e}")
cfg_lock = threading.Lock()


def load_cfg():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"accounts": []}


def save_cfg(data):
    tmp = CONFIG + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CONFIG)


# ----------------------------------------------------------- contrasenyes
def _dpapi(data: bytes, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    buf = ctypes.create_string_buffer(data, len(data))
    bin_ = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    bout = BLOB()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(bin_), "GestorCorreus", None, None, None, 0, ctypes.byref(bout))
    else:
        ok = fn(ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(bout))
    if not ok:
        raise OSError("DPAPI")
    try:
        return ctypes.string_at(bout.pbData, bout.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(bout.pbData)


def store_password(acc, pw):
    acc.pop("pw", None)
    acc.pop("pw_kind", None)
    if pw is None:
        return
    raw = pw.encode("utf-8")
    if os.name == "nt":
        try:
            acc["pw"] = base64.b64encode(_dpapi(raw, True)).decode()
            acc["pw_kind"] = "dpapi"
            return
        except Exception:
            pass
    try:
        import keyring  # opcional
        keyring.set_password(APP_NAME, acc["id"], pw)
        acc["pw_kind"] = "keyring"
        return
    except Exception:
        pass
    acc["pw"] = base64.b64encode(raw).decode()
    acc["pw_kind"] = "b64"


def read_password(acc):
    kind = acc.get("pw_kind")
    try:
        if kind == "dpapi":
            return _dpapi(base64.b64decode(acc["pw"]), False).decode("utf-8")
        if kind == "keyring":
            import keyring
            return keyring.get_password(APP_NAME, acc["id"])
        if kind == "b64":
            return base64.b64decode(acc["pw"]).decode("utf-8")
    except Exception:
        return None
    return None


def forget_password(acc):
    if acc.get("pw_kind") == "keyring":
        try:
            import keyring
            keyring.delete_password(APP_NAME, acc["id"])
        except Exception:
            pass
    acc.pop("pw", None)
    acc.pop("pw_kind", None)


PUBLIC_FIELDS = ("id", "type", "label", "email", "username", "imap_host", "imap_port", "imap_security",
                 "smtp_host", "smtp_port", "smtp_security", "save_password", "delete_mode")


def public(acc):
    d = {k: acc.get(k) for k in PUBLIC_FIELDS}
    d["has_password"] = bool(acc.get("pw_kind"))
    d["connected"] = acc["id"] in sessions and sessions[acc["id"]].imap is not None
    return d


PRESETS = {
    "gmail": {"imap_host": "imap.gmail.com", "imap_port": 993, "imap_security": "ssl",
              "smtp_host": "smtp.gmail.com", "smtp_port": 465, "smtp_security": "ssl"},
    "yahoo": {"imap_host": "imap.mail.yahoo.com", "imap_port": 993, "imap_security": "ssl",
              "smtp_host": "smtp.mail.yahoo.com", "smtp_port": 465, "smtp_security": "ssl"},
}


def normalize(a):
    acc = {k: a.get(k) for k in PUBLIC_FIELDS if k in a}
    acc["type"] = a.get("type") if a.get("type") in PRESETS else "roundcube"
    if acc["type"] in PRESETS:
        acc.update(PRESETS[acc["type"]])
    acc["email"] = (acc.get("email") or "").strip()
    acc["username"] = (acc.get("username") or acc["email"]).strip()
    acc["label"] = (acc.get("label") or acc["email"]).strip()
    acc["imap_host"] = (acc.get("imap_host") or "").strip()
    acc["smtp_host"] = (acc.get("smtp_host") or "").strip()
    acc["imap_port"] = int(acc.get("imap_port") or 993)
    acc["smtp_port"] = int(acc.get("smtp_port") or 465)
    acc["imap_security"] = acc.get("imap_security") or "ssl"
    acc["smtp_security"] = acc.get("smtp_security") or "ssl"
    acc["save_password"] = bool(acc.get("save_password"))
    acc["delete_mode"] = "permanent" if acc.get("delete_mode") == "permanent" else "trash"
    if not acc["email"] or not acc["imap_host"]:
        raise MailError("Cal indicar l'adreça de correu i el servidor IMAP.")
    return acc


# --------------------------------------------------------------- sessions
sessions = {}          # id -> MailSession
session_pw = {}        # id -> contrasenya en memòria (no desada)
jobs = {}


def get_acc(aid):
    for a in load_cfg()["accounts"]:
        if a["id"] == aid:
            return a
    raise MailError("Compte no trobat.")


def get_session(aid, password=None):
    if aid in sessions and password is None:
        return sessions[aid]
    acc = get_acc(aid)
    pw = password or session_pw.get(aid) or read_password(acc)
    if not pw:
        raise NeedPassword()
    s = MailSession(acc, pw)
    with s.lock:
        s.ensure()
    old = sessions.pop(aid, None)
    if old:
        old.close()
    sessions[aid] = s
    session_pw[aid] = pw
    return s


class NeedPassword(Exception):
    pass


def start_job(fn):
    jid = uuid.uuid4().hex
    job = {"status": "running", "done": 0, "total": 0, "result": None, "error": None, "label": None, "cancel": False}
    jobs[jid] = job

    def progress(d, t, label=None):
        job["done"], job["total"] = d, t
        if label:
            job["label"] = label
    progress.cancelled = lambda: job["cancel"]

    def run():
        try:
            job["result"] = fn(progress)
            job["status"] = "done"
        except NeedPassword:
            job["status"], job["error"] = "error", "need_password"
        except migration.Cancelled:
            job["status"], job["error"] = "error", "Cancel·lat. No s'ha acabat l'operació."
        except MailError as e:
            job["status"], job["error"] = "error", str(e)
        except Exception as e:  # noqa
            job["status"], job["error"] = "error", f"Error inesperat: {e}"

    threading.Thread(target=run, daemon=True).start()
    return {"job": jid}


# ------------------------------------------------------------------- API
def api(action, p):
    if action == "state":
        return {"accounts": [public(a) for a in load_cfg()["accounts"]], "config": CONFIG}

    if action == "account_save":
        with cfg_lock:
            data = load_cfg()
            acc = normalize(p["account"])
            existing = next((a for a in data["accounts"] if a["id"] == p["account"].get("id")), None)
            if existing:
                acc["id"] = existing["id"]
                for k in ("pw", "pw_kind"):
                    if k in existing:
                        acc[k] = existing[k]
            else:
                acc["id"] = uuid.uuid4().hex[:12]
            pw = p.get("password")
            if acc["save_password"]:
                if pw:
                    store_password(acc, pw)
            else:
                forget_password(acc)
            if pw:
                session_pw[acc["id"]] = pw
            if existing:
                data["accounts"][data["accounts"].index(existing)] = acc
                old = sessions.pop(acc["id"], None)
                if old:
                    old.close()
            else:
                data["accounts"].append(acc)
            save_cfg(data)
            return {"account": public(acc)}

    if action == "account_delete":
        with cfg_lock:
            data = load_cfg()
            for a in data["accounts"]:
                if a["id"] == p["id"]:
                    forget_password(a)
            data["accounts"] = [a for a in data["accounts"] if a["id"] != p["id"]]
            save_cfg(data)
        s = sessions.pop(p["id"], None)
        if s:
            s.close()
        session_pw.pop(p["id"], None)
        return {}

    if action == "account_test":
        acc = normalize(p["account"])
        pw = p.get("password")
        if not pw and p["account"].get("id"):
            try:
                ex = get_acc(p["account"]["id"])
                pw = session_pw.get(ex["id"]) or read_password(ex)
            except MailError:
                pass
        if not pw:
            raise MailError("Escriu la contrasenya per provar la connexió.")
        s = MailSession(acc, pw)
        try:
            with s.lock:
                s.ensure()
            folders = s.list_folders(with_status=False)
        finally:
            s.close()
        smtp = test_smtp(acc, pw)
        return {"folders": len(folders), "smtp": smtp}

    if action == "connect":
        s = get_session(p["id"], p.get("password") or None)
        if p.get("password") and p.get("remember"):
            with cfg_lock:
                data = load_cfg()
                for a in data["accounts"]:
                    if a["id"] == p["id"]:
                        a["save_password"] = True
                        store_password(a, p["password"])
                save_cfg(data)
        return {"folders": s.list_folders()}

    if action == "disconnect":
        s = sessions.pop(p["id"], None)
        if s:
            s.close()
        session_pw.pop(p["id"], None)
        return {}

    if action == "folders":
        return {"folders": get_session(p["id"]).list_folders()}

    if action == "folder_create":
        s = get_session(p["id"])
        name = p["name"].strip()
        if not name:
            raise MailError("El nom no pot estar buit.")
        if p.get("parent"):
            name = p["parent"] + s.delimiter() + name
        else:
            name = s.root_name(name)
        s.create_folder(name)
        return {"folders": s.list_folders(), "name": name}

    if action == "folder_rename":
        s = get_session(p["id"])
        old = p["old"]
        delim = s.delimiter()
        new_leaf = p["new"].strip()
        if not new_leaf:
            raise MailError("El nom no pot estar buit.")
        parent = old.rsplit(delim, 1)[0] + delim if delim in old else ""
        s.rename_folder(old, parent + new_leaf)
        return {"folders": s.list_folders(), "name": parent + new_leaf}

    if action == "folder_delete":
        s = get_session(p["id"])
        if p["name"].upper() == "INBOX":
            raise MailError("La safata d'entrada no es pot eliminar.")
        s.delete_folder(p["name"])
        return {"folders": s.list_folders()}

    if action == "folder_empty":
        s = get_session(p["id"])
        return start_job(lambda pr: {"count": s.empty_folder(p["name"])})

    if action == "messages":
        s = get_session(p["id"])
        return start_job(lambda pr: s.fetch_messages(p["folder"], pr))

    if action == "delete":
        s = get_session(p["id"])
        acc = get_acc(p["id"])
        permanent = p.get("permanent", acc.get("delete_mode") == "permanent")
        return start_job(lambda pr: s.delete(p["folder"], p["uids"], p.get("uidvalidity"), permanent, pr))

    if action == "move":
        s = get_session(p["id"])
        return start_job(lambda pr: {"count": s.move(p["folder"], p["uids"], p["dest"], p.get("uidvalidity"), pr)})

    if action == "seen":
        s = get_session(p["id"])
        return {"count": s.set_seen(p["folder"], p["uids"], p.get("seen", True), p.get("uidvalidity"))}

    if action == "info":
        s = get_session(p["id"])
        info = s.info()
        info["folders"] = s.list_folders()
        info["trash"] = s.trash_folder()
        return info

    if action == "export":
        s = get_session(p["id"])
        acc = get_acc(p["id"])
        root = p.get("folder") or None
        label = root.split(next((f["delim"] for f in s.folders if f["name"] == root and f["delim"]), "/"))[-1] \
            if root else "tot-el-compte"
        fname = f"{safe_name(acc['email'].split('@')[0])}_{safe_name(label)}_{time.strftime('%Y-%m-%d_%H%M')}.zip"
        path = os.path.join(exports_dir(), fname)
        return start_job(lambda pr: migration.export(s, acc, root, p.get("subfolders", True), path, pr))

    if action == "exports":
        d = exports_dir()
        items = []
        for f in sorted(os.listdir(d), key=lambda x: os.path.getmtime(os.path.join(d, x)), reverse=True):
            if f.endswith(".zip"):
                st = os.stat(os.path.join(d, f))
                items.append({"file": f, "size": st.st_size, "mtime": st.st_mtime})
        return {"dir": d, "files": items[:30]}

    if action == "open_exports":
        f = p.get("file")
        path = os.path.join(exports_dir(), os.path.basename(f)) if f else exports_dir()
        open_path(path, select=bool(f))
        return {}

    if action == "import_plan":
        s = get_session(p["id"])
        up = os.path.join(uploads_dir(), os.path.basename(p["upload"]))
        m = migration.read_manifest(up)
        plan, _ = migration.plan_import(s, m, p.get("parent") or "")
        names = {f["name"] for f in s.folders}
        return {"plan": [{"path": e["path"], "target": t, "count": len(e["messages"]), "exists": t in names or t.upper() == "INBOX"}
                         for e, t in plan]}

    if action == "import":
        s = get_session(p["id"])
        up = os.path.join(uploads_dir(), os.path.basename(p["upload"]))
        if not os.path.exists(up):
            raise MailError("El fitxer ja no hi és. Torna'l a triar.")
        return start_job(lambda pr: migration.do_import(s, up, p.get("parent") or "", p.get("dedupe", True), pr))

    if action == "job_cancel":
        j = jobs.get(p["job"])
        if j:
            j["cancel"] = True
        return {}

    if action == "job":
        j = jobs.get(p["job"])
        if not j:
            raise MailError("Tasca desconeguda.")
        if j["status"] != "running":
            jobs.pop(p["job"], None)
        return j

    raise MailError(f"Acció desconeguda: {action}")


# ---------------------------------------------------------------- servidor
TOKEN = secrets.token_urlsafe(24)
last_ping = [time.time()]


class Handler(BaseHTTPRequestHandler):
    server_version = "GestorCorreus"

    def log_message(self, *a):
        pass

    def _host_ok(self):
        host = self.headers.get("Host", "")
        return host.split(":")[0] in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        path, _, qs = self.path.partition("?")
        if path.startswith("/download/"):
            from urllib.parse import parse_qs, unquote
            if parse_qs(qs).get("t", [""])[0] != TOKEN:
                return self._send(403, {"error": "forbidden"})
            f = os.path.join(exports_dir(), os.path.basename(unquote(path[len("/download/"):])))
            if not os.path.isfile(f):
                return self._send(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Length", str(os.path.getsize(f)))
            self.send_header("Content-Disposition", f'attachment; filename="{os.path.basename(f)}"')
            self.end_headers()
            with open(f, "rb") as fh:
                shutil.copyfileobj(fh, self.wfile, 1024 * 1024)
            return
        if path in ("/", "/index.html"):
            with open(os.path.join(BASE, "ui", "index.html"), encoding="utf-8") as f:
                html = f.read().replace("__TOKEN__", TOKEN)
            return self._send(200, html.encode(), "text/html; charset=utf-8")
        return self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Token") != TOKEN:
            return self._send(403, {"error": "forbidden"})
        last_ping[0] = time.time()
        action = self.path.strip("/").split("/")[-1]
        if action == "upload":
            return self._upload()
        try:
            n = int(self.headers.get("Content-Length") or 0)
            p = json.loads(self.rfile.read(n) or b"{}")
            if action == "ping":
                return self._send(200, {"ok": True})
            return self._send(200, {"ok": True, **(api(action, p) or {})})
        except NeedPassword:
            return self._send(200, {"ok": False, "need_password": True,
                                    "error": "Cal la contrasenya d'aquest compte."})
        except MailError as e:
            return self._send(200, {"ok": False, "error": str(e)})
        except Exception as e:  # noqa
            return self._send(200, {"ok": False, "error": f"Error inesperat: {e}"})


def _upload(self):
    n = int(self.headers.get("Content-Length") or 0)
    up = uuid.uuid4().hex + ".zip"
    dest = os.path.join(uploads_dir(), up)
    try:
        with open(dest, "wb") as fh:
            left = n
            while left > 0:
                b = self.rfile.read(min(1024 * 1024, left))
                if not b:
                    break
                fh.write(b)
                left -= len(b)
        m = migration.read_manifest(dest)
        return self._send(200, {"ok": True, "upload": up, **migration.summary(m)})
    except MailError as e:
        try:
            os.remove(dest)
        except OSError:
            pass
        return self._send(200, {"ok": False, "error": str(e)})


Handler._upload = _upload


def find_app_browser():
    cands = []
    if os.name == "nt":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            root = os.environ.get(env)
            if root:
                cands += [os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(root, "Google", "Chrome", "Application", "chrome.exe")]
    for n in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        w = shutil.which(n)
        if w:
            cands.append(w)
    return next((c for c in cands if c and os.path.exists(c)), None)


def main():
    port = int(os.environ.get("GESTOR_PORT", "0"))
    clean_uploads()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    if os.environ.get("GESTOR_NO_UI"):
        log(url, TOKEN)
        while True:
            time.sleep(3600)

    if not os.environ.get("GESTOR_BROWSER"):
        try:
            import webview  # pywebview: finestra pròpia amb WebView2
            if hasattr(webview, "settings"):
                webview.settings["ALLOW_DOWNLOADS"] = True
            webview.create_window(APP_NAME, url, width=1440, height=920, min_size=(1100, 700))
            webview.start()
            return
        except Exception as e:  # sense pywebview o sense WebView2 -> navegador
            log("pywebview no disponible:", e)

    log(f"{APP_NAME} en marxa a {url}\nTanca aquesta finestra per aturar el programa.")
    br = find_app_browser()
    if br:
        base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
        prof = os.path.join(base, "GestorCorreus", "navegador")
        subprocess.Popen([br, f"--app={url}", f"--user-data-dir={prof}", "--window-size=1440,920"])
    else:
        webbrowser.open(url)
    # S'atura sol quan la finestra porta una estona tancada.
    while time.time() - last_ping[0] < 180:
        time.sleep(5)


if __name__ == "__main__":
    main()
