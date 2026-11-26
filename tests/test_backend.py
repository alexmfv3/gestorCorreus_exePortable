"""Proves del motor amb un servidor IMAP simulat. Executa: python tests/test_backend.py"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "tests")]
os.environ["GESTOR_CORREUS_HOME"] = tempfile.mkdtemp()

import imap_client  # noqa: E402
import fake_imap  # noqa: E402

imap_client.MailSession.imap_factory = fake_imap.factory
import app  # noqa: E402


def wait(job):
    while True:
        st = app.api("job", {"job": job})
        if st["status"] != "running":
            assert st["status"] == "done", st
            return st["result"]
        time.sleep(0.05)


def main():
    assert imap_client.imap_utf7_decode(imap_client.imap_utf7_encode("Però & Cía")) == "Però & Cía"
    assert imap_client.uid_set([1, 2, 3, 5, 7, 8]) == "1:3,5,7:8"

    # contrasenya desada (DPAPI a Windows)
    acc = app.api("account_save", {"account": {"type": "roundcube", "email": "jo@x.cat", "imap_host": "mail.x.cat",
                                               "save_password": True}, "password": "secret"})["account"]
    stored = app.load_cfg()["accounts"][0]
    if os.name == "nt":
        assert stored["pw_kind"] == "dpapi", stored["pw_kind"]
    assert app.read_password(stored) == "secret"
    app.session_pw.clear()

    folders = app.api("connect", {"id": acc["id"]})["folders"]
    names = [f["name"] for f in folders]
    assert "INBOX" in names and "Clients/Acme/2026" in names and "Però" in names

    res = wait(app.api("messages", {"id": acc["id"], "folder": "INBOX"})["job"])
    msgs = res["messages"]
    assert len(msgs) == 1500, len(msgs)
    info = [m["uid"] for m in msgs if m["from_email"] == "ofertas@infojobs.net"]
    assert len(info) == 60
    r = wait(app.api("delete", {"id": acc["id"], "folder": "INBOX", "uids": info, "uidvalidity": res["uidvalidity"]})["job"])
    assert r == {"count": 60, "trash": "Trash"}, r
    r = wait(app.api("move", {"id": acc["id"], "folder": "INBOX", "uids": [msgs[0]["uid"]], "dest": "Clients/Acme/2026",
                              "uidvalidity": res["uidvalidity"]})["job"])
    assert r["count"] == 1
    assert app.api("folder_create", {"id": acc["id"], "name": "Pressupostos", "parent": "Clients/Bosch"})["name"] == "Clients/Bosch/Pressupostos"
    assert app.api("folder_rename", {"id": acc["id"], "old": "Clients", "new": "Clients antics"})["name"] == "Clients antics"
    q = app.api("info", {"id": acc["id"]})["quota"]
    assert q["supported"] and q["limit"] == 1024 ** 3
    g = app.api("account_test", {"account": {"type": "gmail", "email": "a@gmail.com"}, "password": "sec ret"})
    assert g["folders"] > 0
    # Yahoo: servidor predefinit, contrasenya d'aplicació amb espais, carpetes per nom
    y = app.api("account_save", {"account": {"type": "yahoo", "email": "algu@yahoo.es", "imap_host": "x",
                                             "save_password": False}, "password": "sec ret"})["account"]
    assert y["imap_host"] == "imap.mail.yahoo.com" and y["smtp_host"] == "smtp.mail.yahoo.com", y
    yf = {f["name"]: f["special"] for f in app.api("connect", {"id": y["id"]})["folders"]}
    assert yf["Bulk"] == "spam" and yf["Draft"] == "drafts" and yf["Trash"] == "trash" and yf["Sent"] == "sent" and yf["Archive"] == "archive", yf
    yr = wait(app.api("messages", {"id": y["id"], "folder": "INBOX"})["job"])
    r = wait(app.api("delete", {"id": y["id"], "folder": "INBOX", "uids": [yr["messages"][0]["uid"]],
                                "uidvalidity": yr["uidvalidity"]})["job"])
    assert r == {"count": 1, "trash": "Trash"}, r
    # Migració: GENCAT (amb subcarpetes) -> servidor amb prefix «INBOX.» i delimitador «.»
    import shutil
    import zipfile
    dst = app.api("account_save", {"account": {"type": "roundcube", "email": "courier@altre.cat", "imap_host": "m",
                                               "save_password": True}, "password": "secret"})["account"]
    app.api("connect", {"id": dst["id"]})
    ex = wait(app.api("export", {"id": acc["id"], "folder": "GENCAT", "subfolders": True})["job"])
    assert ex["folders"] == 4 and ex["messages"] == 9, ex
    with zipfile.ZipFile(ex["path"]) as z:
        assert "correus/GENCAT/TSOC/Expedients/000002.eml" in z.namelist()
    shutil.copy(ex["path"], os.path.join(app.uploads_dir(), "t.zip"))
    imp = wait(app.api("import", {"id": dst["id"], "upload": "t.zip"})["job"])
    assert imp["imported"] == 9 and "INBOX.GENCAT.TSOC.Expedients" in imp["created"], imp
    fc = fake_imap._shared["courier@altre.cat"]
    assert len(fc.boxes["INBOX.GENCAT.TSOC"]) == 4 and len(fc.boxes["INBOX.GENCAT.TSOC.Expedients"]) == 2
    again = wait(app.api("import", {"id": dst["id"], "upload": "t.zip"})["job"])
    assert again["imported"] == 0 and again["skipped"] == 9, again
    print("OK: totes les proves del motor han passat")


if __name__ == "__main__":
    main()
