import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
import imap_client  # noqa
import fake_imap  # noqa

imap_client.MailSession.imap_factory = fake_imap.factory
import app  # noqa

app.main()
