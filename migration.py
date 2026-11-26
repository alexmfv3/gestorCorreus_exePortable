"""Gestor de Correus - migració: exporta una carpeta (amb subcarpetes) a .zip i la importa a un altre compte.

Format del fitxer (.zip):
    manifest.json                     índex: carpetes (noms reals), marcadors, dates, Message-ID
    correus/GENCAT/000001.eml         un correu per fitxer, format estàndard RFC 822
    correus/GENCAT/TSOC/000001.eml
"""
import json
import os
import re
import zipfile
from datetime import datetime

from imap_client import MailError, message_id

FORMAT = "gestor-correus-migracio"
VERSION = 1
BATCH_BYTES = 15 * 1024 * 1024
BATCH_MAX = 50
GMAIL_ROOT = re.compile(r"^\[(Gmail|Google Mail)\]$", re.I)
SKIP_SPECIAL = {"all", "flagged", "important"}   # vistes de Gmail que duplicarien correus
MAP_SPECIAL = {"inbox", "sent", "drafts", "trash", "spam", "archive"}


class Cancelled(Exception):
    pass


def safe(part):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", part).strip(" .")
    return s[:80] or "_"


def _parts(f, delim):
    return f["name"].split(delim) if delim else [f["name"]]


def plan_export(sess, root, include_sub=True):
    """Llista de (carpeta, camí relatiu) a exportar. root=None vol dir tot el compte."""
    folders = sess.list_folders(with_status=False)
    prefix, _ = sess.namespace()
    out = []
    if root:
        rf = next((f for f in folders if f["name"] == root), None)
        if not rf:
            raise MailError(f"No existeix la carpeta «{root}».")
        d = rf["delim"]
        leaf = _parts(rf, d)[-1]
        leaf = "INBOX" if leaf.upper() == "INBOX" else leaf
        out.append((rf, [leaf]))
        if include_sub and d:
            for f in folders:
                if f["name"].startswith(root + d):
                    out.append((f, [leaf] + f["name"][len(root) + len(d):].split(d)))
    else:
        for f in folders:
            if f["special"] in SKIP_SPECIAL:
                continue
            d = f["delim"]
            name = f["name"]
            if prefix and name.startswith(prefix) and name.upper() != "INBOX":
                name = name[len(prefix):]
            p = name.split(d) if d else [name]
            if GMAIL_ROOT.match(p[0]):
                if len(p) == 1:
                    continue
                p = p[1:]
            out.append((f, p))
    out.sort(key=lambda x: [s.lower() for s in x[1]])
    return out


def export(sess, account, root, include_sub, path, progress):
    items = plan_export(sess, root, include_sub)
    progress(0, 0, "Comptant correus…")
    sizes = {}
    for f, _ in items:
        if f["selectable"]:
            sizes[f["name"]] = sess.uid_sizes(f["name"])
    total = sum(len(v) for v in sizes.values())
    manifest = {"format": FORMAT, "version": VERSION, "created": datetime.now().astimezone().isoformat(timespec="seconds"),
                "source": {"email": account.get("email"), "type": account.get("type"), "root": root},
                "folders": []}
    done, used = 0, set()
    tmp = path + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            for i, (f, parts) in enumerate(items):
                d = "correus/" + "/".join(safe(p) for p in parts)
                while d in used:
                    d += "_"
                used.add(d)
                entry = {"path": parts, "special": f["special"], "dir": d, "messages": []}
                batch, bsize = [], 0
                pending = sizes.get(f["name"], [])

                def flush(b):
                    nonlocal done
                    if not b:
                        return
                    if progress.cancelled():
                        raise Cancelled()
                    for r in sess.fetch_raw(f["name"], b):
                        fn = f"{d}/{len(entry['messages']) + 1:06d}.eml"
                        z.writestr(fn, r["raw"])
                        entry["messages"].append({"file": fn, "flags": r["flags"], "date": r["date"],
                                                  "msgid": message_id(r["raw"]), "size": len(r["raw"])})
                    done += len(b)
                    progress(done, total, "Exportant «" + " › ".join(parts) + "»")

                for uid, size in pending:
                    if batch and (bsize + size > BATCH_BYTES or len(batch) >= BATCH_MAX):
                        flush(batch)
                        batch, bsize = [], 0
                    batch.append(uid)
                    bsize += size
                flush(batch)
                manifest["folders"].append(entry)
            z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return {"file": os.path.basename(path), "path": path, "size": os.path.getsize(path),
            "folders": len(manifest["folders"]), "messages": done}


def read_manifest(path):
    try:
        with zipfile.ZipFile(path) as z:
            m = json.loads(z.read("manifest.json").decode("utf-8"))
    except (zipfile.BadZipFile, KeyError, ValueError):
        raise MailError("Aquest fitxer no és una exportació del Gestor de Correus.")
    if m.get("format") != FORMAT:
        raise MailError("Aquest fitxer no és una exportació del Gestor de Correus.")
    return m


def summary(m):
    return {"source": m.get("source", {}), "created": m.get("created"),
            "folders": [{"path": f["path"], "count": len(f["messages"]), "special": f.get("special", "")}
                        for f in m["folders"]],
            "messages": sum(len(f["messages"]) for f in m["folders"])}


def plan_import(sess, m, parent):
    """Calcula el nom de destí de cada carpeta de l'exportació."""
    folders = sess.list_folders(with_status=False)
    delim = sess.delimiter()
    special = {}
    for f in folders:
        if f["special"] and f["selectable"] and f["special"] not in special:
            special[f["special"]] = f["name"]
    top = {}
    if not parent:
        for e in m["folders"]:
            if len(e["path"]) == 1 and e.get("special") in MAP_SPECIAL:
                if e["special"] == "inbox" or e["path"][0].upper() == "INBOX":
                    top[e["path"][0]] = "INBOX"
                elif e["special"] in special:
                    top[e["path"][0]] = special[e["special"]]
    out = []
    for e in m["folders"]:
        parts = [p.replace(delim, "-") if delim else p for p in e["path"]]
        if parent:
            target = delim.join([parent] + parts)
        else:
            first = e["path"][0]
            base = top.get(first) or ("INBOX" if first.upper() == "INBOX" else sess.root_name(parts[0]))
            target = delim.join([base] + parts[1:])
        out.append((e, target))
    return out, delim


def do_import(sess, path, parent, dedupe, progress):
    m = read_manifest(path)
    plan, delim = plan_import(sess, m, parent)
    existing = {f["name"].upper() if f["name"].upper() == "INBOX" else f["name"] for f in sess.folders}
    created = []
    progress(0, 0, "Creant carpetes…")
    for _, target in plan:
        bits = target.split(delim)
        for i in range(1, len(bits) + 1):
            name = delim.join(bits[:i])
            key = "INBOX" if name.upper() == "INBOX" else name
            if key in existing:
                continue
            if sess.ensure_folder(name):
                created.append(name)
            existing.add(key)
    pre = {f["name"] for f in sess.list_folders(with_status=False)} - set(created)
    total = sum(len(e["messages"]) for e, _ in plan)
    done = imported = skipped = failed = 0
    errors = []
    with zipfile.ZipFile(path) as z:
        for e, target in plan:
            ids = set()
            if dedupe and e["messages"] and target in pre:
                progress(done, total, f"Comprovant duplicats a «{target}»…")
                ids = sess.message_ids(target)
            for msg in e["messages"]:
                if progress.cancelled():
                    raise Cancelled()
                mid = msg.get("msgid")
                if dedupe and mid and mid in ids:
                    skipped += 1
                else:
                    try:
                        sess.append(target, z.read(msg["file"]), msg.get("flags") or [], msg.get("date"))
                        imported += 1
                        if mid:
                            ids.add(mid)
                    except (MailError, KeyError) as ex:
                        failed += 1
                        if len(errors) < 15:
                            errors.append(f"{target}: {ex}")
                done += 1
                if done % 5 == 0 or done == total:
                    progress(done, total, "Important a «" + " › ".join(e["path"]) + "»")
    return {"created": created, "imported": imported, "skipped": skipped, "failed": failed,
            "errors": errors, "folders": [t for _, t in plan]}
