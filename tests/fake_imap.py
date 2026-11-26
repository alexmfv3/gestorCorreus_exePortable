"""IMAP fals que imita les respostes d'imaplib, per provar el Gestor sense servidor real."""
import random
import re
from datetime import datetime, timedelta, timezone
from email.header import Header

import imap_client as ic


class FakeIMAP:
    error = ic.imaplib.IMAP4.error
    abort = ic.imaplib.IMAP4.abort

    def __init__(self, gmail=False, yahoo=False, courier=False):
        random.seed(4)
        self.gmail = gmail
        self.courier = courier
        self.d = "." if courier else "/"
        self.flags = {"INBOX": [], "Sent": ["\\Sent"], "Trash": ["\\Trash"], "Spam": ["\\Junk"],
                      "Feina": [], "Factures": [], "Factures/2026": [], "Però": []}
        if courier:  # com Courier/Dovecot antic: tot penja d'«INBOX.» i el delimitador és «.»
            self.flags = {"INBOX": [], "INBOX.Sent": ["\\Sent"], "INBOX.Trash": ["\\Trash"], "INBOX.Feina": []}
        elif yahoo:
            self.flags = {"INBOX": [], "Sent": [], "Draft": [], "Archive": [], "Bulk": [], "Trash": [],
                          "Feina": [], "Feina/Ofertes": []}
        elif gmail:
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
            for k in ("GENCAT", "GENCAT/TSOC", "GENCAT/TSOC/Expedients", "GENCAT/Altres"):
                self.flags[k] = []
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
        if courier:
            return
        for i in range(5):
            self._add("[Gmail]/Paperera" if gmail else "Trash", "Vell", "vell@x.com", f"Esborrat {i}", now, True)
        if not gmail and not yahoo:
            self._rich()
            for box, n in (("GENCAT", 3), ("GENCAT/TSOC", 4), ("GENCAT/TSOC/Expedients", 2)):
                for i in range(n):
                    self._add(box, "Generalitat", "noreply@gencat.cat", f"{box.split('/')[-1]}: comunicació {i+1}",
                              now - timedelta(days=i + 1), i % 2 == 0)

    def _add(self, box, name, addr, subj, dt, seen):
        uid = self.next_uid[box]
        self.next_uid[box] += 1
        frm = f"{Header(name, 'utf-8').encode()} <{addr}>"
        mid = f"<{abs(hash((box, uid, subj))) % 10**12}.{uid}@fake.test>"
        hdr = (f"From: {frm}\r\nSubject: {Header(subj, 'utf-8').encode()}\r\nDate: {dt:%a, %d %b %Y %H:%M:%S +0000}\r\n"
               f"Message-ID: {mid}\r\n\r\n")
        raw = hdr.encode() + f"Hola,\r\naixò és el cos de «{subj}». Adéu!\r\n".encode()
        self.boxes[box][uid] = {"hdr": hdr.encode(), "raw": raw, "dt": dt, "size": random.randint(3000, 400000),
                                "flags": {"\\Seen"} if seen else set()}

    def _rich(self):
        from email.message import EmailMessage
        import io, zipfile
        now = datetime(2026, 11, 26, 9, 30, tzinfo=timezone.utc)
        m = EmailMessage()
        m["From"] = '"Marta Puig" <marta.puig@gmail.com>'
        m["To"] = "jo@empresa.cat, Anna Roca <anna@empresa.cat>"
        m["Cc"] = "pere@empresa.cat"
        m["Subject"] = "Reunió de dimarts: acta i propers passos"
        m["Message-ID"] = "<reunio-123@gmail.com>"
        m["Date"] = "Thu, 26 Nov 2026 09:30:00 +0000"
        m.set_content("Hola,\nAdjunto l'acta.\n")
        m.add_alternative(
            '<html><head><style>.t{color:#0a7}</style><script>parent.document.body.innerHTML="HACKED"</script></head>'
            '<body><div style="max-width:600px"><img src="cid:logo@x" alt="logo" width="120">'
            '<h2 class="t">Reunió de dimarts</h2><p>Hola a tots,</p><p>Us passo l\'<b>acta</b> i els punts:</p>'
            '<ul><li>Pressupost <i>2027</i></li><li>Calendari<ul><li>Gener</li><li>Febrer</li></ul></li></ul>'
            '<p><img src="https://tracker.example.com/pixel.gif" width="1" height="1">'
            '<img src="https://picsum.photos/400/120" alt="foto remota"></p>'
            '<p onclick="alert(1)">Més info a <a href="https://gencat.cat">gencat.cat</a> o '
            '<a href="mailto:secretaria@empresa.cat">escriu a secretaria</a>.</p><p>Salutacions,<br>Marta</p></div>'
            '</body></html>', subtype="html")
        import base64 as _b64
        png = _b64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAIAAABLbSncAAAAEklEQVR4nGNoYPiPFTEMSwkAUmV/gcOb8i0AAAAASUVORK5CYII=")
        m.get_payload()[1].add_related(png, maintype="image", subtype="png", cid="<logo@x>")
        m.add_attachment(b"%PDF-1.4 acta", maintype="application", subtype="pdf", filename="Acta reunió.pdf")
        m.add_attachment(b"MZ fake", maintype="application", subtype="octet-stream", filename="instal·lador.exe")
        self._add_raw("INBOX", m.as_bytes(), now, False)
        t = EmailMessage()
        t["From"] = "Servidor <noreply@hosting.cat>"
        t["To"] = "jo@empresa.cat"
        t["Subject"] = "Avís en text pla"
        t["Message-ID"] = "<pla-1@hosting.cat>"
        t["Date"] = "Thu, 26 Nov 2026 08:00:00 +0000"
        t.set_content("Bon dia,\n\nAquest correu és text pla.\n  - Línia amb sagnat\nVisita https://hosting.cat/estat per veure l'estat.\n\n<b>Això no és negreta</b>\n")
        self._add_raw("INBOX", t.as_bytes(), now - timedelta(hours=1), False)

    def _add_raw(self, box, raw, dt, seen):
        uid = self.next_uid[box]
        self.next_uid[box] += 1
        hdr = raw.split(b"\n\n", 1)[0].replace(b"\r", b"").replace(b"\n", b"\r\n") + b"\r\n\r\n"
        self.boxes[box][uid] = {"hdr": hdr, "raw": raw, "dt": dt, "size": len(raw), "flags": {"\\Seen"} if seen else set()}

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
        return "OK", [b"IMAP4rev1 UIDPLUS MOVE QUOTA SPECIAL-USE IDLE NAMESPACE"]

    def namespace(self):
        return "OK", [b'(("INBOX." ".")) NIL NIL' if self.courier else b'(("" "/")) NIL NIL']

    def append(self, mailbox, flags, date_time, message):
        n = self._unq(mailbox)
        if n not in self.boxes:
            return "NO", [b"[TRYCREATE] Mailbox doesn't exist"]
        raw = bytes(message)
        hdr = raw.split(b"\r\n\r\n", 1)[0] + b"\r\n\r\n"
        dt = datetime.strptime(date_time.strip('"'), "%d-%b-%Y %H:%M:%S %z") if date_time else datetime.now(timezone.utc)
        uid = self.next_uid[n]
        self.next_uid[n] += 1
        self.boxes[n][uid] = {"hdr": hdr, "raw": raw, "dt": dt, "size": len(raw),
                              "flags": set(re.findall(r"\\\w+", flags or ""))}
        return "OK", [f"[APPENDUID 1 {uid}] Append completed".encode()]

    def noop(self):
        return "OK", [b""]

    def logout(self):
        return "BYE", [b""]

    def list(self):
        out = []
        for k, fl in self.flags.items():
            enc = ic.imap_utf7_encode(k)
            kids = any(o.startswith(k + self.d) for o in self.flags)
            if "\\Noselect" in fl:
                out.append(f'(\\HasChildren \\Noselect) "{self.d}" "{enc}"'.encode()); continue
            f = " ".join(["\\HasChildren" if kids else "\\HasNoChildren"] + fl)
            out.append(f'({f}) "{self.d}" "{enc}"'.encode() if k != "Feina" else f'({f}) "{self.d}" {enc}'.encode())
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
            return "NO", [b"[ALREADYEXISTS] Mailbox already exists"]
        if self.courier and not n.startswith("INBOX."):
            return "NO", [b"[CANNOT] Invalid mailbox name"]
        self.flags[n], self.boxes[n], self.next_uid[n] = [], {}, 1
        return "OK", [b""]

    def rename(self, a, b):
        a, b = self._unq(a), self._unq(b)
        for k in [k for k in self.flags if k == a or k.startswith(a + self.d)]:
            nk = b + k[len(a):]
            self.flags[nk] = self.flags.pop(k)
            self.boxes[nk] = self.boxes.pop(k)
            self.next_uid[nk] = self.next_uid.pop(k)
        return "OK", [b""]

    def delete(self, name):
        n = self._unq(name)
        if any(k.startswith(n + self.d) for k in self.flags):
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
            what = args[1].upper()
            for i, u in enumerate(self._uids(args[0])):
                m = b[u]
                if "BODY.PEEK[]" in what:
                    d = m["dt"].strftime("%d-%b-%Y %H:%M:%S +0000")
                    out.append((f'{i+1} (UID {u} FLAGS ({" ".join(sorted(m["flags"]))}) INTERNALDATE "{d}" '
                                f'BODY[] {{{len(m["raw"])}}}'.encode(), m["raw"]))
                    out.append(b")")
                    continue
                if "MESSAGE-ID" in what:
                    h = re.search(rb"Message-ID: [^\r]+\r\n", m["hdr"])
                    h = (h.group(0) if h else b"") + b"\r\n"
                    out.append((f'{i+1} (UID {u} BODY[HEADER.FIELDS (MESSAGE-ID)] {{{len(h)}}}'.encode(), h))
                    out.append(b")")
                    continue
                if "BODY" not in what:
                    out.append(f'{i+1} (UID {u} RFC822.SIZE {m["size"]})'.encode())
                    continue
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
        _shared[key] = FakeIMAP(cfg.get("type") == "gmail", cfg.get("type") == "yahoo", "courier" in (key or ""))
    return _shared[key]
