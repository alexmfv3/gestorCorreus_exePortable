"""Gestor de Correus - motor IMAP (només biblioteca estàndard)."""
import base64
import email
import email.utils
import imaplib
import re
import smtplib
import socket
import ssl
import threading
from datetime import datetime, timezone
from email.header import decode_header, make_header

imaplib._MAXLINE = 50_000_000  # carpetes molt grans

FETCH_CHUNK = 400
OP_CHUNK = 500

TRASH_NAMES = {"trash", "paperera", "papelera", "deleted items", "deleted messages",
               "elementos eliminados", "elements suprimits", "corbeille", "bin"}
SPAM_NAMES = {"spam", "junk", "correu brossa", "correo no deseado", "junk e-mail", "junk email"}
SENT_NAMES = {"sent", "enviats", "enviados", "sent items", "sent messages", "elementos enviados"}
DRAFT_NAMES = {"drafts", "esborranys", "borradores"}


class MailError(Exception):
    pass


# ---------------------------------------------------------------- UTF-7 IMAP
def imap_utf7_decode(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "&":
            j = s.find("-", i)
            if j == -1:
                out.append(s[i:])
                break
            chunk = s[i + 1:j]
            if chunk == "":
                out.append("&")
            else:
                b64 = chunk.replace(",", "/")
                b64 += "=" * (-len(b64) % 4)
                try:
                    out.append(base64.b64decode(b64).decode("utf-16-be"))
                except Exception:
                    out.append(s[i:j + 1])
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def imap_utf7_encode(s: str) -> str:
    out, buf = [], []

    def flush():
        if buf:
            b = base64.b64encode("".join(buf).encode("utf-16-be")).decode().rstrip("=")
            out.append("&" + b.replace("/", ",") + "-")
            buf.clear()

    for c in s:
        if 0x20 <= ord(c) <= 0x7E:
            flush()
            out.append("&-" if c == "&" else c)
        else:
            buf.append(c)
    flush()
    return "".join(out)


def q(name: str) -> str:
    """Nom de carpeta (UTF-8) -> argument IMAP entre cometes."""
    enc = imap_utf7_encode(name)
    return '"' + enc.replace("\\", "\\\\").replace('"', '\\"') + '"'


def uid_set(uids):
    uids = sorted({int(u) for u in uids})
    parts, i = [], 0
    while i < len(uids):
        j = i
        while j + 1 < len(uids) and uids[j + 1] == uids[j] + 1:
            j += 1
        parts.append(str(uids[i]) if i == j else f"{uids[i]}:{uids[j]}")
        i = j + 1
    return ",".join(parts)


def chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def dec(value) -> str:
    if value is None:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return str(value)


def _b(x):
    return x if isinstance(x, (bytes, bytearray)) else str(x).encode()


# ------------------------------------------------------------------ parsing
LIST_RE = re.compile(rb'^\((?P<flags>[^)]*)\)\s+(?P<delim>"(?:[^"\\]|\\.)*"|NIL)\s*(?P<name>.*)$', re.I)


def parse_list(data):
    folders = []
    items = list(data or [])
    for it in items:
        if it is None:
            continue
        if isinstance(it, tuple):
            m = LIST_RE.match(it[0].strip())
            raw = it[1]
        else:
            m = LIST_RE.match(it.strip())
            raw = None
        if not m:
            continue
        flags = m.group("flags").decode(errors="replace").split()
        d = m.group("delim").decode(errors="replace")
        delim = None if d.upper() == "NIL" else d[1:-1].replace("\\\\", "\\").replace('\\"', '"')
        if raw is None:
            raw = m.group("name").strip()
            if raw.startswith(b'"') and raw.endswith(b'"'):
                raw = raw[1:-1].replace(b'\\"', b'"').replace(b"\\\\", b"\\")
        name = imap_utf7_decode(raw.decode("utf-8", errors="replace"))
        folders.append({"name": name, "delim": delim, "flags": flags})
    return folders


def classify(folder):
    fl = {f.lower() for f in folder["flags"]}
    leaf = folder["name"].split(folder["delim"])[-1] if folder["delim"] else folder["name"]
    low = leaf.lower()
    if folder["name"].upper() == "INBOX":
        return "inbox"
    for flag, kind in (("\\trash", "trash"), ("\\junk", "spam"), ("\\sent", "sent"),
                       ("\\drafts", "drafts"), ("\\all", "all"), ("\\flagged", "flagged"),
                       ("\\important", "important"), ("\\archive", "archive")):
        if flag in fl:
            return kind
    if low in TRASH_NAMES:
        return "trash"
    if low in SPAM_NAMES:
        return "spam"
    if low in SENT_NAMES:
        return "sent"
    if low in DRAFT_NAMES:
        return "drafts"
    return ""


META_UID = re.compile(rb"UID (\d+)")
META_SIZE = re.compile(rb"RFC822\.SIZE (\d+)")
META_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
META_DATE = re.compile(rb'INTERNALDATE "([^"]+)"')
NEW_REC = re.compile(rb"^\d+ \(")


def parse_fetch(data):
    recs, cur = [], None
    for it in data or []:
        if isinstance(it, tuple):
            cur = {"meta": it[0], "hdr": it[1] or b""}
            recs.append(cur)
        elif isinstance(it, (bytes, bytearray)):
            if NEW_REC.match(it):
                cur = {"meta": bytes(it), "hdr": b""}
                recs.append(cur)
            elif cur is not None:
                cur["meta"] += b" " + bytes(it)
    out = []
    for r in recs:
        m = META_UID.search(r["meta"])
        if not m:
            continue
        uid = int(m.group(1))
        size = META_SIZE.search(r["meta"])
        flags = META_FLAGS.search(r["meta"])
        idate = META_DATE.search(r["meta"])
        flags_l = flags.group(1).decode(errors="replace").lower().split() if flags else []
        try:
            msg = email.message_from_bytes(r["hdr"])
        except Exception:
            msg = {}
        name, addr = email.utils.parseaddr(dec(msg.get("From", "")))
        ts = None
        if idate:
            try:
                ts = datetime.strptime(idate.group(1).decode(), "%d-%b-%Y %H:%M:%S %z").timestamp()
            except Exception:
                ts = None
        if ts is None:
            try:
                ts = email.utils.parsedate_to_datetime(msg.get("Date")).timestamp()
            except Exception:
                ts = 0
        addr = (addr or "").strip().lower()
        out.append({
            "uid": uid,
            "from_name": (name or "").strip().strip('"') or (addr.split("@")[0] if addr else "(desconegut)"),
            "from_email": addr or "(sense adreça)",
            "subject": " ".join(dec(msg.get("Subject", "")).split()) or "(sense assumpte)",
            "ts": ts,
            "size": int(size.group(1)) if size else 0,
            "seen": "\\seen" in flags_l,
            "flagged": "\\flagged" in flags_l,
        })
    return out


def parse_quota(qdata):
    """Retorna dict amb used/limit en bytes, o None si no hi ha límit d'emmagatzematge."""
    res = {}
    for item in qdata or []:
        if isinstance(item, tuple):
            item = b" ".join(x for x in item if isinstance(x, bytes))
        if not item:
            continue
        for m in re.finditer(rb"(\w+) (\d+) (\d+)", item):
            res[m.group(1).decode().upper()] = (int(m.group(2)), int(m.group(3)))
    return res


# ------------------------------------------------------------------ session
class MailSession:
    """Una connexió IMAP per compte, protegida amb un lock."""

    imap_factory = None  # per a proves

    def __init__(self, cfg, password):
        self.cfg = cfg
        self.password = password
        self.lock = threading.RLock()
        self.imap = None
        self.caps = set()
        self.folders = []
        self._selected = None

    # -- connexió
    def _connect(self):
        c = self.cfg
        host, port, sec = c["imap_host"], int(c.get("imap_port") or 993), c.get("imap_security", "ssl")
        try:
            if MailSession.imap_factory:
                im = MailSession.imap_factory(c)
            elif sec == "ssl":
                im = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=40)
            else:
                im = imaplib.IMAP4(host, port, timeout=40)
                if sec == "starttls":
                    im.starttls(ssl.create_default_context())
        except (socket.gaierror, ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as e:
            raise MailError(f"No s'ha pogut connectar a {host}:{port} ({e})")
        try:
            pw = self.password.replace(" ", "") if c.get("type") == "gmail" else self.password
            im.login(c.get("username") or c.get("email"), pw)
        except imaplib.IMAP4.error as e:
            msg = e.args[0].decode(errors="replace") if e.args and isinstance(e.args[0], bytes) else str(e)
            hint = ""
            if c.get("type") == "gmail":
                hint = " A Gmail cal fer servir una «contrasenya d'aplicació» (vegeu Com connectar-lo)."
            raise MailError(f"Usuari o contrasenya incorrectes: {msg}.{hint}")
        typ, dat = im.capability()
        self.caps = set(dat[0].decode().upper().split()) if dat and dat[0] else set()
        self.imap = im
        self._selected = None

    def ensure(self):
        if self.imap is not None:
            try:
                typ, _ = self.imap.noop()
                if typ == "OK":
                    return
            except Exception:
                pass
            self.close()
        self._connect()

    def close(self):
        try:
            if self.imap:
                self.imap.logout()
        except Exception:
            pass
        self.imap = None
        self._selected = None

    def _check(self, typ, dat, what):
        if typ != "OK":
            txt = dat[0].decode(errors="replace") if dat and isinstance(dat[0], bytes) else str(dat)
            raise MailError(f"{what}: {txt}")
        return dat

    def _select(self, folder, readonly=False):
        key = (folder, readonly)
        if self._selected == key:
            return self._uidvalidity
        typ, dat = self.imap.select(q(folder), readonly=readonly)
        self._check(typ, dat, f"No s'ha pogut obrir la carpeta «{folder}»")
        uv = self.imap.response("UIDVALIDITY")[1]
        self._uidvalidity = int(uv[0]) if uv and uv[0] else 0
        self._selected = key
        return self._uidvalidity

    def _run(self, fn):
        with self.lock:
            try:
                self.ensure()
                return fn()
            except (imaplib.IMAP4.abort, OSError, ssl.SSLError):
                self.close()
                self.ensure()
                return fn()

    # -- carpetes
    def list_folders(self, with_status=True):
        def go():
            typ, dat = self.imap.list()
            self._check(typ, dat, "No s'han pogut llegir les carpetes")
            fl = parse_list(dat)
            for f in fl:
                f["special"] = classify(f)
                f["selectable"] = "\\noselect" not in {x.lower() for x in f["flags"]} and \
                                  "\\nonexistent" not in {x.lower() for x in f["flags"]}
                f["messages"] = f["unseen"] = f["size"] = None
                if with_status and f["selectable"]:
                    items = "(MESSAGES UNSEEN SIZE)" if "STATUS=SIZE" in self.caps else "(MESSAGES UNSEEN)"
                    try:
                        typ, sd = self.imap.status(q(f["name"]), items)
                        if typ == "OK" and sd and sd[0]:
                            line = sd[0] if isinstance(sd[0], bytes) else sd[0][0]
                            for k, v in re.findall(rb"(MESSAGES|UNSEEN|SIZE) (\d+)", line):
                                f[k.decode().lower()] = int(v)
                    except imaplib.IMAP4.error:
                        pass
            order = {"inbox": 0, "": 5, "sent": 2, "drafts": 3, "archive": 4, "all": 6,
                     "important": 6, "flagged": 6, "spam": 7, "trash": 8}
            fl.sort(key=lambda f: (order.get(f["special"], 5), f["name"].lower()))
            self.folders = fl
            return fl
        return self._run(go)

    def trash_folder(self):
        if not self.folders:
            self.list_folders(with_status=False)
        for f in self.folders:
            if f["special"] == "trash" and f["selectable"]:
                return f["name"]
        return None

    def delimiter(self):
        if not self.folders:
            self.list_folders(with_status=False)
        for f in self.folders:
            if f["delim"]:
                return f["delim"]
        return "/"

    def create_folder(self, name):
        def go():
            self._check(*self.imap.create(q(name)), f"No s'ha pogut crear «{name}»")
            try:
                self.imap.subscribe(q(name))
            except Exception:
                pass
        self._run(go)

    def rename_folder(self, old, new):
        def go():
            if self._selected and self._selected[0] == old:
                try:
                    self.imap.close()
                except Exception:
                    pass
                self._selected = None
            self._check(*self.imap.rename(q(old), q(new)), f"No s'ha pogut reanomenar «{old}»")
            try:
                self.imap.unsubscribe(q(old))
                self.imap.subscribe(q(new))
            except Exception:
                pass
        self._run(go)

    def delete_folder(self, name):
        def go():
            if self._selected and self._selected[0] == name:
                try:
                    self.imap.close()
                except Exception:
                    pass
                self._selected = None
            try:
                self.imap.unsubscribe(q(name))
            except Exception:
                pass
            self._check(*self.imap.delete(q(name)), f"No s'ha pogut eliminar «{name}»")
        self._run(go)

    def empty_folder(self, name):
        def go():
            self._select(name)
            typ, dat = self.imap.uid("SEARCH", None, "ALL")
            uids = dat[0].split() if typ == "OK" and dat and dat[0] else []
            for ch in chunks(uids, OP_CHUNK):
                self._check(*self.imap.uid("STORE", uid_set(ch), "+FLAGS.SILENT", r"(\Deleted)"), "Error en marcar")
            self._check(*self.imap.expunge(), "Error en buidar")
            return len(uids)
        return self._run(go)

    # -- missatges
    def fetch_messages(self, folder, progress=None):
        def go():
            uv = self._select(folder, readonly=True)
            typ, dat = self.imap.uid("SEARCH", None, "ALL")
            self._check(typ, dat, "Error en cercar")
            uids = [int(x) for x in (dat[0].split() if dat and dat[0] else [])]
            total = len(uids)
            out = []
            if progress:
                progress(0, total)
            for ch in chunks(uids, FETCH_CHUNK):
                typ, fd = self.imap.uid(
                    "FETCH", uid_set(ch),
                    "(UID RFC822.SIZE FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
                self._check(typ, fd, "Error en llegir els correus")
                out.extend(parse_fetch(fd))
                if progress:
                    progress(len(out), total)
            out.sort(key=lambda m: m["ts"] or 0, reverse=True)
            return {"uidvalidity": uv, "messages": out}
        return self._run(go)

    def _verify(self, folder, uidvalidity):
        uv = self._select(folder)
        if uidvalidity and uv and int(uidvalidity) != uv:
            raise MailError("La carpeta ha canviat al servidor. Prem «Actualitza» i torna-ho a provar.")

    def _expunge(self, uids):
        if "UIDPLUS" in self.caps:
            self._check(*self.imap.uid("EXPUNGE", uid_set(uids)), "Error en eliminar")
        else:
            self._check(*self.imap.expunge(), "Error en eliminar")

    def move(self, folder, uids, dest, uidvalidity=None, progress=None):
        if folder == dest:
            raise MailError("La carpeta de destinació és la mateixa que l'origen.")

        def go():
            self._verify(folder, uidvalidity)
            done = 0
            for ch in chunks(uids, OP_CHUNK):
                s = uid_set(ch)
                if "MOVE" in self.caps:
                    self._check(*self.imap.uid("MOVE", s, q(dest)), f"No s'ha pogut moure a «{dest}»")
                else:
                    self._check(*self.imap.uid("COPY", s, q(dest)), f"No s'ha pogut copiar a «{dest}»")
                    self._check(*self.imap.uid("STORE", s, "+FLAGS.SILENT", r"(\Deleted)"), "Error en marcar")
                    self._expunge(ch)
                done += len(ch)
                if progress:
                    progress(done, len(uids))
            return done
        return self._run(go)

    def delete(self, folder, uids, uidvalidity=None, permanent=False, progress=None):
        trash = None if permanent else self.trash_folder()
        if trash and trash != folder:
            return {"count": self.move(folder, uids, trash, uidvalidity, progress), "trash": trash}

        def go():
            self._verify(folder, uidvalidity)
            done = 0
            for ch in chunks(uids, OP_CHUNK):
                self._check(*self.imap.uid("STORE", uid_set(ch), "+FLAGS.SILENT", r"(\Deleted)"), "Error en marcar")
                self._expunge(ch)
                done += len(ch)
                if progress:
                    progress(done, len(uids))
            return {"count": done, "trash": None}
        return self._run(go)

    def set_seen(self, folder, uids, seen, uidvalidity=None):
        def go():
            self._verify(folder, uidvalidity)
            for ch in chunks(uids, OP_CHUNK):
                self._check(*self.imap.uid("STORE", uid_set(ch), "+FLAGS.SILENT" if seen else "-FLAGS.SILENT",
                                           r"(\Seen)"), "Error en marcar")
            return len(uids)
        return self._run(go)

    # -- informació
    def info(self):
        def go():
            quota = {"supported": "QUOTA" in self.caps, "unlimited": None, "used": None,
                     "limit": None, "messages_used": None, "messages_limit": None, "root": None}
            if quota["supported"]:
                try:
                    typ, dat = self.imap.getquotaroot("INBOX")
                    if typ == "OK":
                        roots, qd = (dat + [[], []])[:2]
                        res = parse_quota(qd)
                        if "STORAGE" in res:
                            used, limit = res["STORAGE"]
                            quota["used"] = used * 1024
                            quota["limit"] = limit * 1024 if limit else None
                        if "MESSAGE" in res:
                            quota["messages_used"], quota["messages_limit"] = res["MESSAGE"]
                        quota["unlimited"] = quota["limit"] is None
                except imaplib.IMAP4.error:
                    quota["supported"] = False
            return {"capabilities": sorted(self.caps), "quota": quota}
        return self._run(go)


def test_smtp(cfg, password):
    host = cfg.get("smtp_host")
    if not host:
        return None
    port, sec = int(cfg.get("smtp_port") or 465), cfg.get("smtp_security", "ssl")
    try:
        if sec == "ssl":
            s = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
        else:
            s = smtplib.SMTP(host, port, timeout=20)
            s.ehlo()
            if sec == "starttls":
                s.starttls(context=ssl.create_default_context())
                s.ehlo()
        s.login(cfg.get("username") or cfg.get("email"), password)
        s.quit()
        return "ok"
    except Exception as e:
        return f"SMTP: {e}"
