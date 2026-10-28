import smtplib
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import config
import mailer
import runner
from guess import guess_company, guess_name
from store import Store, ingest

TEMPLATE = """## WITH_COMPANY
Subject: Hello {company}

{greeting}
Pitch for {company}.

## NO_COMPANY
Subject: Hello

{greeting}
Generic pitch.
"""


def make_cfg(tmp, **over):
    pdir = Path(tmp)
    (pdir / "inbox").mkdir(exist_ok=True)
    (pdir / "template.txt").write_text(TEMPLATE)
    cfg = dict(config.DEFAULTS, GMAIL_ADDRESS="me@gmail.com", GMAIL_APP_PASSWORD="x",
               SENDER_NAME="Me", CHECK_UNSUBSCRIBES="0", dir=pdir, profile="t",
               daily_limit=3, min_delay=0, max_delay=0, start_hour=0, end_hour=24)
    cfg.update(over)
    return cfg


class FakeSender:
    sent = []
    fail = {}

    def __init__(self, cfg):
        pass

    def send(self, msg):
        to = msg["To"]
        if to in FakeSender.fail:
            raise FakeSender.fail[to]
        FakeSender.sent.append(msg)

    def close(self):
        pass


class Guess(unittest.TestCase):
    def test_company(self):
        self.assertEqual(guess_company("a@acme-robotics.com"), "Acme Robotics")
        self.assertEqual(guess_company("a@mail.tata.co.in"), "Tata")
        self.assertEqual(guess_company("a@gmail.com"), "")
        self.assertEqual(guess_company("a@yahoo.co.in"), "")

    def test_name(self):
        self.assertEqual(guess_name("priya.sharma@x.com"), "Priya")
        self.assertEqual(guess_name("hr@x.com"), "")
        self.assertEqual(guess_name("careers@x.com"), "")
        self.assertEqual(guess_name("jd@x.com"), "")
        self.assertEqual(guess_name("x1234@x.com"), "")


class Ingest(unittest.TestCase):
    def test_csv_and_plain(self):
        with tempfile.TemporaryDirectory() as t:
            s = Store(Path(t) / "db")
            a = Path(t) / "a.csv"
            a.write_text("email,name,company\nPriya@Acme.com,,\nbad,,\nhr@foo.in,Bob,Foo Ltd\npriya@acme.com,,\nblock@x.com,,\n")
            st = ingest(s, a, {"block@x.com"})
            self.assertEqual(st, {"added": 2, "duplicate": 1, "invalid": 1, "optout": 1})
            rows = {r["email"]: r for r in s.queued(10)}
            self.assertEqual((rows["priya@acme.com"]["name"], rows["priya@acme.com"]["company"]), ("Priya", "Acme"))
            self.assertEqual(rows["hr@foo.in"]["company"], "Foo Ltd")
            b = Path(t) / "b.txt"
            b.write_text("one@zeta.org\ntwo@zeta.org, three@zeta.org\n")
            self.assertEqual(ingest(s, b, set())["added"], 3)


class Render(unittest.TestCase):
    def test_variants(self):
        with tempfile.TemporaryDirectory() as t:
            tpl = mailer.load_templates(self._write(t))
            subj, body = mailer.render(tpl, {"name": "Priya", "company": "Acme"})
            self.assertEqual(subj, "Hello Acme")
            self.assertIn("Hi Priya,", body)
            subj, body = mailer.render(tpl, {"name": "", "company": ""})
            self.assertIn("Hi there,", body)
            self.assertIn("Generic", body)

    def test_unedited_template_refused(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "template.txt"
            p.write_text("Subject: [EDIT: x]")
            with self.assertRaises(mailer.TemplateError):
                mailer.load_templates(p)

    def _write(self, t):
        p = Path(t) / "template.txt"
        p.write_text(TEMPLATE)
        return p

    def test_unsubscribe_detection(self):
        raw = (b"From: Bob <bob@x.com>\nSubject: Re: hi\nContent-Type: text/plain\n\n"
               b"Please unsubscribe me\n\nOn Mon, Me wrote:\n> reply unsubscribe to stop\n")
        self.assertEqual(mailer.is_unsubscribe(raw), "bob@x.com")
        quoted_only = (b"From: Bob <bob@x.com>\nSubject: Re: hi\nContent-Type: text/plain\n\n"
                       b"Sounds great, call me.\n\n> Not relevant? reply \"unsubscribe\"\n")
        self.assertEqual(mailer.is_unsubscribe(quoted_only), "")


class Run(unittest.TestCase):
    def setUp(self):
        FakeSender.sent, FakeSender.fail = [], {}

    def go(self, cfg, **kw):
        return runner.run(cfg, sender_factory=FakeSender, sleep=lambda s: None, **kw)

    def test_cap_and_resume_no_duplicates(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_cfg(t)
            (cfg["dir"] / "inbox" / "l.csv").write_text("email\n" + "\n".join(f"p{i}x@co{i}.com" for i in range(5)))
            self.assertEqual(self.go(cfg)["sent"], 3)
            self.assertEqual(self.go(cfg)["sent"], 0)  # cap reached today
            recipients = [m["To"] for m in FakeSender.sent if m["To"] != "me@gmail.com"]
            self.assertEqual(len(recipients), len(set(recipients)))
            self.assertFalse(list((cfg["dir"] / "inbox").glob("*.csv")))  # moved to processed
            cfg["daily_limit"] = 10  # "next day": more room, same db
            self.assertEqual(self.go(cfg)["sent"], 2)
            self.assertEqual(self.go(cfg)["sent"], 0)

    def test_permanent_failure_and_optout(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_cfg(t)
            (cfg["dir"] / "optout.txt").write_text("skip@x.com\n")
            (cfg["dir"] / "inbox" / "l.csv").write_text("email\nbad@x.com\nskip@x.com\nok@x.com\n")
            FakeSender.fail["bad@x.com"] = smtplib.SMTPRecipientsRefused({"bad@x.com": (550, b"no")})
            res = self.go(cfg)
            self.assertEqual(res, {"sent": 1, "failed": 1})
            counts = Store(cfg["dir"] / "sent.db").counts()
            self.assertEqual(counts, {"sent": 1, "failed": 1})

    def test_outside_hours_and_dry_run(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_cfg(t, start_hour=9, end_hour=10)
            (cfg["dir"] / "inbox" / "l.csv").write_text("email\na@x.com\n")
            res = runner.run(cfg, sender_factory=FakeSender, sleep=lambda s: None,
                             now=lambda: datetime(2026, 1, 1, 22, 0))
            self.assertEqual(res["sent"], 0)
            self.assertEqual(FakeSender.sent, [])
            res = runner.run(cfg, dry_run=True, sender_factory=FakeSender)
            self.assertEqual(FakeSender.sent, [])
            self.assertEqual(Store(cfg["dir"] / "sent.db").counts(), {"queued": 1})

    def test_auth_failure_aborts(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_cfg(t)
            (cfg["dir"] / "inbox" / "l.csv").write_text("email\na@x.com\n")
            FakeSender.fail["a@x.com"] = smtplib.SMTPAuthenticationError(535, b"bad")
            with self.assertRaises(SystemExit):
                self.go(cfg)
            self.assertEqual(Store(cfg["dir"] / "sent.db").counts(), {"queued": 1})
            self.assertFalse((cfg["dir"] / ".lock").exists())


class Attachment(unittest.TestCase):
    def test_resume_attached(self):
        with tempfile.TemporaryDirectory() as t:
            (Path(t) / "cv.pdf").write_bytes(b"%PDF-1.4 fake")
            cfg = make_cfg(t, RESUME_PATH="cv.pdf")
            msg = mailer.build_message(cfg, "a@x.com", "s", "b")
            names = [p.get_filename() for p in msg.iter_attachments()]
            self.assertEqual(names, ["cv.pdf"])
            self.assertIn("unsubscribe", msg.get_body().get_content())


if __name__ == "__main__":
    unittest.main()
