"""Gestor de Correus - llegir correus (HTML o text pla), netejar HTML i muntar respostes/reenviaments."""
import base64
import email
import email.utils
import html
import io
import mimetypes
import os
import re
import zipfile
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser

MAX_TOTAL = 20 * 1024 * 1024          # límit d'adjunts per missatge
MAX_INLINE_IMG = 4 * 1024 * 1024      # imatges incrustades (cid:) que es mostren

# Tipus de fitxer que no es poden adjuntar (executables, scripts, dreceres, imatges de disc...)
DANGEROUS = {
    "exe", "com", "scr", "pif", "bat", "cmd", "msi", "msp", "mst", "msc", "cpl", "dll", "sys", "drv", "ocx",
    "vbs", "vbe", "js", "jse", "wsf", "wsh", "wsc", "ps1", "ps1xml", "ps2", "psc1", "psm1", "psd1",
    "jar", "hta", "lnk", "url", "scf", "reg", "inf", "ins", "isp", "application", "gadget", "appx", "appxbundle",
    "msix", "msixbundle", "appref-ms", "iso", "img", "vhd", "vhdx", "chm", "hlp", "sct", "shb", "shs", "xbap",
    "ade", "adp", "mde", "accde", "xll", "xlam", "ppam", "docm", "dotm", "xlsm", "xltm", "pptm", "potm",
    "ppsm", "sldm", "action", "command", "csh", "ksh", "sh", "app", "apk", "deb", "rpm", "elf", "bin", "run",
}
ARCHIVES = {"zip"}


def ext_of(name):
    return os.path.splitext(name or "")[1].lower().lstrip(".")


def danger_reason(name, data=None):
    """Retorna el motiu si el fitxer no es pot adjuntar, o None si és segur."""
    e = ext_of(name)
    if e in DANGEROUS:
        return f"Els fitxers .{e} no es poden adjuntar (poden contenir programes perillosos)."
    if e in ARCHIVES and data is not None:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                for n in z.namelist():
                    if ext_of(n) in DANGEROUS:
                        return f"El .zip conté un fitxer perillós ({os.path.basename(n)})."
        except zipfile.BadZipFile:
            pass
        except RuntimeError:  # zip xifrat: no es pot revisar
            return "El .zip està protegit amb contrasenya i no es pot revisar."
    return None


# ------------------------------------------------------------------ lectura
def _text(part):
    try:
        return part.get_content()
    except Exception:
        raw = part.get_payload(decode=True) or b""
        cs = part.get_content_charset() or "utf-8"
        try:
            return raw.decode(cs, errors="replace")
        except LookupError:
            return raw.decode("utf-8", errors="replace")


def _addr_list(msg, h):
    vals = msg.get_all(h, [])
    out = []
    for name, addr in email.utils.getaddresses([str(v) for v in vals]):
        if addr or name:
            out.append({"name": name, "email": addr.lower()})
    return out


def _filename(part, i):
    fn = part.get_filename()
    if fn:
        return fn
    ct = part.get_content_type()
    if ct == "message/rfc822":
        return f"missatge-{i}.eml"
    return f"adjunt-{i}{mimetypes.guess_extension(ct) or '.bin'}"


def parse(raw):
    msg = email.message_from_bytes(raw, policy=policy.default)
    body_html = body_text = None
    try:
        b = msg.get_body(preferencelist=("html",))
        if b is not None:
            body_html = _text(b)
        t = msg.get_body(preferencelist=("plain",))
        if t is not None:
            body_text = _text(t)
    except Exception:
        pass
    if body_html is None and body_text is None and not msg.is_multipart():
        body_text = _text(msg)

    # imatges incrustades (cid:)
    cids, used = {}, set()
    for part in msg.walk():
        cid = part.get("Content-ID")
        if cid and part.get_content_maintype() == "image":
            data = part.get_payload(decode=True) or b""
            if len(data) <= MAX_INLINE_IMG:
                cids[cid.strip("<> ")] = "data:%s;base64,%s" % (part.get_content_type(), base64.b64encode(data).decode())
    if body_html and cids:
        def sub(m):
            k = m.group(2).strip()
            if k in cids:
                used.add(k)
                return m.group(1) + cids[k]
            return m.group(0)
        body_html = re.sub(r'''(["'(]\s*)cid:([^"')\s>]+)''', sub, body_html, flags=re.I)

    atts, parts = [], []
    for i, part in enumerate(msg.iter_attachments(), 1):
        cid = (part.get("Content-ID") or "").strip("<> ")
        if cid and cid in used:
            continue
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            data = payload[0].as_bytes() if isinstance(payload, list) and payload else part.get_payload(decode=True) or b""
        else:
            data = part.get_payload(decode=True) or b""
        name = _filename(part, i)
        parts.append({"name": name, "ctype": part.get_content_type(), "data": data})
        atts.append({"idx": len(parts) - 1, "name": name, "size": len(data), "ctype": part.get_content_type(),
                     "dangerous": ext_of(name) in DANGEROUS})
    try:
        ts = email.utils.parsedate_to_datetime(msg.get("Date")).timestamp()
    except Exception:
        ts = None
    frm = _addr_list(msg, "From")
    return {
        "subject": " ".join(str(msg.get("Subject", "") or "").split()) or "(sense assumpte)",
        "from": frm[0] if frm else {"name": "", "email": ""},
        "to": _addr_list(msg, "To"), "cc": _addr_list(msg, "Cc"), "reply_to": _addr_list(msg, "Reply-To"),
        "date": ts, "message_id": (msg.get("Message-ID") or "").strip(),
        "references": " ".join(str(msg.get("References") or "").split()),
        "html": body_html, "text": body_text, "attachments": atts, "_parts": parts,
    }


# ---------------------------------------------------------- neteja d'HTML
OK_TAGS = {"a", "abbr", "b", "blockquote", "br", "caption", "center", "code", "col", "colgroup", "dd", "del", "div",
           "dl", "dt", "em", "font", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "img", "ins", "li", "ol", "p",
           "pre", "q", "s", "small", "span", "strike", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th",
           "thead", "tr", "tt", "u", "ul"}
DROP_WITH_CONTENT = {"script", "style", "head", "title", "iframe", "object", "embed", "noscript", "template", "svg",
                     "math", "form", "button", "select", "textarea", "frameset", "frame", "applet", "meta", "link"}
OK_ATTRS = {"href", "src", "alt", "title", "width", "height", "align", "valign", "colspan", "rowspan", "border",
            "cellpadding", "cellspacing", "bgcolor", "color", "face", "size", "style", "dir", "start", "type"}
VOID = {"br", "hr", "img", "col"}


class _Clean(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            if tag not in ("meta", "link"):
                self.skip += 1
            return
        if self.skip or tag not in OK_TAGS:
            return
        keep = []
        for k, v in attrs:
            k = k.lower()
            v = v or ""
            if k not in OK_ATTRS:
                continue
            if k == "href" and not re.match(r"^\s*(https?:|mailto:|#)", v, re.I):
                continue
            if k == "src" and not v.startswith("data:image/"):
                continue  # sense imatges remotes ni rastrejadors
            if k == "style":
                if re.search(r"url\s*\(|expression|javascript|@import|behavior|position\s*:\s*fixed", v, re.I):
                    continue
            keep.append(f'{k}="{html.escape(v, quote=True)}"')
        if tag == "img" and not any(k.startswith("src=") for k in keep):
            return  # imatge remota bloquejada: no deixem una etiqueta buida
        if tag == "a":
            keep.append('target="_blank" rel="noopener noreferrer"')
        self.out.append(f"<{tag}{' ' if keep else ''}{' '.join(keep)}>")

    handle_startendtag = handle_starttag

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT and tag not in ("meta", "link"):
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in OK_TAGS or tag in VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html.escape(data, quote=False))


def sanitize(fragment):
    p = _Clean()
    p.feed(fragment or "")
    p.close()
    return "".join(p.out)


def text_to_html(text):
    t = html.escape(text or "")
    t = re.sub(r"(https?://[^\s<>&]+)", r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', t)
    return t.replace("\r\n", "\n").replace("\n", "<br>")


def body_as_safe_html(view):
    if view.get("html"):
        return sanitize(view["html"])
    return text_to_html(view.get("text") or "")


class _ToText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out, self.lists, self.skip, self.quote = [], [], 0, 0

    def _nl(self):
        if self.out and not self.out[-1].endswith("\n"):
            self.out.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script", "head"):
            self.skip += 1
        elif tag == "br":
            self.out.append("\n")
        elif tag in ("p", "div", "h1", "h2", "h3", "tr", "table"):
            self._nl()
        elif tag in ("ul", "ol"):
            self._nl()
            self.lists.append([tag, 0])
        elif tag == "li":
            self._nl()
            depth = max(0, len(self.lists) - 1)
            if self.lists and self.lists[-1][0] == "ol":
                self.lists[-1][1] += 1
                mark = f"{self.lists[-1][1]}."
            else:
                mark = "-" if depth == 0 else "·"
            self.out.append("   " * depth + mark + " ")
        elif tag == "blockquote":
            self._nl()
            self.quote += 1

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("ul", "ol") and self.lists:
            self.lists.pop()
            self._nl()
        elif tag in ("p", "div", "li", "h1", "h2", "h3"):
            self._nl()
        elif tag == "blockquote":
            self.quote = max(0, self.quote - 1)
            self._nl()

    def handle_data(self, data):
        if self.skip:
            return
        data = re.sub(r"\s+", " ", data)
        if self.quote and (not self.out or self.out[-1].endswith("\n")):
            data = "> " * self.quote + data.lstrip()
        self.out.append(data)


def html_to_text(fragment):
    p = _ToText()
    p.feed(fragment or "")
    p.close()
    txt = "".join(p.out)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(l.rstrip() for l in txt.split("\n"))).strip() + "\n"


# --------------------------------------------------------------- muntatge
ADDR_RE = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def parse_addrs(s):
    out, bad = [], []
    for name, addr in email.utils.getaddresses([s.replace(";", ",")] if s else []):
        if not addr and not name:
            continue
        if not ADDR_RE.match(addr or ""):
            bad.append(addr or name)
        else:
            out.append((name, addr))
    return out, bad


def fmt_addrs(lst):
    return ", ".join(email.utils.formataddr((n, a)) for n, a in lst)


def build(acc, to, cc, bcc, subject, body_html, files, in_reply_to=None, references=None):
    """files: llista de (nom, bytes)."""
    msg = EmailMessage()
    name = (acc.get("sender_name") or "").strip()
    msg["From"] = email.utils.formataddr((name, acc["email"])) if name else acc["email"]
    msg["To"] = fmt_addrs(to)
    if cc:
        msg["Cc"] = fmt_addrs(cc)
    if bcc:
        msg["Bcc"] = fmt_addrs(bcc)
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=acc["email"].split("@")[-1])
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = ((references or "") + " " + in_reply_to).strip()
    msg["X-Mailer"] = "Gestor de Correus"
    clean = sanitize(body_html)
    msg.set_content(html_to_text(clean))
    msg.add_alternative(
        '<!DOCTYPE html><html><head><meta charset="utf-8"></head>'
        '<body style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5;color:#1d1d29">'
        f"{clean}</body></html>", subtype="html")
    for fname, data in files:
        ctype = mimetypes.guess_type(fname)[0] or "application/octet-stream"
        maint, sub = ctype.split("/", 1)
        if ctype == "message/rfc822":
            maint, sub = "application", "octet-stream"
        msg.add_attachment(data, maintype=maint, subtype=sub, filename=fname)
    return msg
