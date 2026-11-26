import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import imap_client  # noqa
import fake_imap  # noqa

imap_client.MailSession.imap_factory = fake_imap.factory
import app  # noqa


def _fake_send(cfg, pw, msg):  # SMTP simulat: desa el missatge enviat
    n = len([f for f in os.listdir("/tmp") if f.startswith("gc_sent_")])
    with open(f"/tmp/gc_sent_{n + 1}.eml", "wb") as fh:
        fh.write(msg.as_bytes())


app.send_mail = _fake_send
app.main()
