"""IMAP fals que imita les respostes d'imaplib, per provar el Gestor sense servidor real."""
import random
import re
from datetime import datetime, timedelta, timezone
from email.header import Header

import imap_client as ic


class FakeIMAP:
    error = ic.imaplib.IMAP4.error
    abort = ic.imaplib.IMAP4.abort

    def __init__(self, gmail=False):
        random.seed(4)
        self.gmail = gmail
        self.flags = {"INBOX": [], "Sent": ["\\Sent"], "Trash": ["\\Trash"], "Spam": ["\\Junk"],
                      "Feina": [], "Factures": [], "Factures/2026": [], "Però": []}
        if gmail:
            self.flags = {"INBOX": [], "[Gmail]": ["\\Noselect"], "[Gmail]/Tots els correus": ["\\All"],
                          "[Gmail]/Paperera": ["\\Trash"], "[Gmail]/Enviats": ["\\Sent"], "[Gmail]/Spam": ["\\Junk"],
                          "[Gmail]/Destacats": ["\\Flagged"], "Feina": [], "Feina/Ofertes": []}
        else:
            self.flags["Clients"] = []
            for c in ["Acme", "Bosch", "Cafès Roure", "Diputació", "Eòlia", "Fundació X", "Grup Sant Joan"]:
                self.flags[f"Clients/{c}"] = []
                for y in ("2024", "2025", "2026"):
                    self.flags[f"Clients/{c}/{y}"] = []
            for i in range(1, 13):
                self.flags[f"Projectes/P{i:02d}"] = []
            self.flags["Projectes/P01/Documentació"] = []
            self.flags["Projectes/P01/Reunions"] = []
            self.flags["Factures/2025"] = []
        self.boxes = {k: {} for k in self.flags}
        self.next_uid = {k: 1 for k in self.flags}
        self.sel = None
        senders = [("InfoJobs", "ofertas@infojobs.net", "Ofertes de feina disponibles", 60),
                   ("InfoJobs", "alertas@push.infojobs.net", "Nova oferta: Programador/a", 18),
                   ("LinkedIn", "jobs-noreply@linkedin.com", "Noves feines per a tu", 42),
                   ("Amazon.es", "pedidos@amazon.es", "El teu comanda s'ha enviat", 25),
                   ("Caixa d'Enginyers", "info@caixaenginyers.com", "Extracte mensual", 12),
                   ("Ajuntament", "noreply@bcn.cat", "Avís: rebut IBI", 4),
                   ("Marta Puig", "marta.puig@gmail.com", "Sopar de divendres?", 6),
                   ("Glovo", "promo@glovoapp.com", "50% de descompte avui 🍕", 33)]
        now = datetime(2026, 11, 18, 10, 0, tzinfo=timezone.utc)
        for name, addr, subj, n in senders:
            for i in range(n):
                self._add("INBOX", name, addr, f"{subj} #{i+1}", now - timedelta(hours=random.randint(1, 4000)),
                          random.random() < .6)
        for i in range(1300):
            self._add("INBOX", f"Persona {i%250}", f"p{i%250}@exemple.cat", f"Missatge {i}",
                      now - timedelta(hours=random.randint(1, 9000)), True)
        for i in range(5):
            self._add("[Gmail]/Paperera" if gmail else "Trash", "Vell", "vell@x.com", f"Esborrat {i}", now, True)

    def _add(self, box, name, addr, subj, dt, seen):
        uid = self.next_uid[box]
        self.next_uid[box] += 1
        frm = f"{Header(name, 'utf-8').encode()} <{addr}>"
        hdr = f"From: {frm}\r\nSubject: {Header(subj, 'utf-8').encode()}\r\nDate: {dt:%a, %d %b %Y %H:%M:%S +0000}\r\n\r\n"
        self.boxes[box][uid] = {"hdr": hdr.encode(), "dt": dt, "size": random.randint(3000, 400000),
                                "flags": {"\\Seen"} if seen else set()}

    @staticmethod
    def _unq(n):
        n = n.strip()
        if n.startswith('"'):
            n = n[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        return ic.imap_utf7_decode(n)

    def _uids(self, spec):
        res = set()
        keys = self.boxes[self.sel]
        mx = max(keys) if keys else 0
        for part in spec.split(","):
            if ":" in part:
                a, b = part.split(":")
                a, b = int(a), (mx if b == "*" else int(b))
                res |= {u for u in keys if a <= u <= b}
            elif int(part) in keys:
                res.add(int(part))
        return sorted(res)

    # --- API d'imaplib
    def login(self, u, p):
        if p != "secret":
            raise self.error(b"[AUTHENTICATIONFAILED] Invalid credentials")
        return "OK", [b"Logged in"]

    def capability(self):
        return "OK", [b"IMAP4rev1 UIDPLUS MOVE QUOTA SPECIAL-USE IDLE"]

    def noop(self):
        return "OK", [b""]

    def logout(self):
        return "BYE", [b""]

    def list(self):
        out = []
        for k, fl in self.flags.items():
            enc = ic.imap_utf7_encode(k)
            kids = any(o.startswith(k + "/") for o in self.flags)
            if "\\Noselect" in fl:
                out.append(f'(\\HasChildren \\Noselect) "/" "{enc}"'.encode()); continue
            f = " ".join(["\\HasChildren" if kids else "\\HasNoChildren"] + fl)
            out.append(f'({f}) "/" "{enc}"'.encode() if k != "Feina" else f'({f}) "/" {enc}'.encode())
        return "OK", out

    def status(self, name, items):
        n = self._unq(name)
        if n not in self.boxes: return "NO", [b"no"]
        b = self.boxes[n]
        un = sum(1 for m in b.values() if "\\Seen" not in m["flags"])
        return "OK", [f'{name} (MESSAGES {len(b)} UNSEEN {un})'.encode()]

    def select(self, name, readonly=False):
        n = self._unq(name)
        if n not in self.boxes:
            return "NO", [b"Mailbox doesn't exist"]
        self.sel = n
        self._uv = 1000 + list(self.boxes).index(n)
        return "OK", [str(len(self.boxes[n])).encode()]

    def response(self, code):
        return code, [str(self._uv).encode()]

    def close(self):
        self.sel = None
        return "OK", [b""]

    def expunge(self):
        b = self.boxes[self.sel]
        for u in [u for u, m in b.items() if "\\Deleted" in m["flags"]]:
            del b[u]
        return "OK", [b""]

    def create(self, name):
        n = self._unq(name)
        if n in self.flags:
            return "NO", [b"Mailbox already exists"]
        self.flags[n], self.boxes[n], self.next_uid[n] = [], {}, 1
        return "OK", [b""]

    def rename(self, a, b):
        a, b = self._unq(a), self._unq(b)
        for k in [k for k in self.flags if k == a or k.startswith(a + "/")]:
            nk = b + k[len(a):]
            self.flags[nk] = self.flags.pop(k)
            self.boxes[nk] = self.boxes.pop(k)
            self.next_uid[nk] = self.next_uid.pop(k)
        return "OK", [b""]

    def delete(self, name):
        n = self._unq(name)
        if any(k.startswith(n + "/") for k in self.flags):
            return "NO", [b"Mailbox has children"]
        for d in (self.flags, self.boxes, self.next_uid):
            d.pop(n, None)
        return "OK", [b""]

    def subscribe(self, n):
        return "OK", [b""]

    unsubscribe = subscribe

    def getquotaroot(self, box):
        used = sum(m["size"] for b in self.boxes.values() for m in b.values()) // 1024
        return "OK", [[b'"INBOX" ""'], [f'"" (STORAGE {used} 1048576)'.encode()]]

    def uid(self, cmd, *args):
        cmd = cmd.upper()
        b = self.boxes[self.sel]
        if cmd == "SEARCH":
            return "OK", [" ".join(map(str, sorted(b))).encode()]
        if cmd == "FETCH":
            out = []
            for i, u in enumerate(self._uids(args[0])):
                m = b[u]
                fl = " ".join(sorted(m["flags"]))
                d = m["dt"].strftime("%d-%b-%Y %H:%M:%S +0000")
                if u % 3 == 0:  # FLAGS després del literal (com Gmail)
                    out.append((f'{i+1} (UID {u} RFC822.SIZE {m["size"]} INTERNALDATE "{d}" '
                                f'BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{{len(m["hdr"])}}}'.encode(), m["hdr"]))
                    out.append(f" FLAGS ({fl}))".encode())
                else:
                    out.append((f'{i+1} (UID {u} RFC822.SIZE {m["size"]} FLAGS ({fl}) INTERNALDATE "{d}" '
                                f'BODY[HEADER.FIELDS (FROM SUBJECT DATE)] {{{len(m["hdr"])}}}'.encode(), m["hdr"]))
                    out.append(b")")
            return "OK", out
        if cmd == "STORE":
            spec, op, flags = args
            fl = set(re.findall(r"\\\w+", flags))
            for u in self._uids(spec):
                if op.startswith("+"):
                    b[u]["flags"] |= fl
                else:
                    b[u]["flags"] -= fl
            return "OK", [b""]
        if cmd in ("MOVE", "COPY"):
            dest = self._unq(args[1])
            if dest not in self.boxes:
                return "NO", [b"[TRYCREATE] Mailbox doesn't exist"]
            for u in self._uids(args[0]):
                m = b[u] if cmd == "COPY" else b.pop(u)
                nu = self.next_uid[dest]
                self.next_uid[dest] += 1
                self.boxes[dest][nu] = {**m, "flags": set(m["flags"]) - {"\\Deleted"}}
            return "OK", [b""]
        if cmd == "EXPUNGE":
            for u in self._uids(args[0]):
                if "\\Deleted" in b[u]["flags"]:
                    del b[u]
            return "OK", [b""]
        return "BAD", [b"unknown"]


_shared = {}


def factory(cfg):
    key = cfg.get("email")
    if key not in _shared:
        _shared[key] = FakeIMAP(cfg.get("type") == "gmail")
    return _shared[key]
