"""SQLite queue: one row per recipient, so nobody is ever emailed twice."""
import csv
import re
import sqlite3
from datetime import datetime
from pathlib import Path

from guess import guess_company, guess_name

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
FIND_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS leads (
                 email TEXT PRIMARY KEY, name TEXT, company TEXT, source TEXT,
                 status TEXT NOT NULL DEFAULT 'queued',
                 attempts INTEGER NOT NULL DEFAULT 0,
                 error TEXT, sent_at TEXT, added_at TEXT)"""
        )
        self.db.commit()

    def add(self, email, name, company, source) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO leads (email,name,company,source,added_at) VALUES (?,?,?,?,?)",
            (email.lower(), name, company, source, datetime.now().isoformat(timespec="seconds")),
        )
        self.db.commit()
        return cur.rowcount == 1

    def queued(self, limit):
        return self.db.execute(
            "SELECT * FROM leads WHERE status='queued' ORDER BY added_at, rowid LIMIT ?", (limit,)
        ).fetchall()

    def mark_sent(self, email):
        self.db.execute(
            "UPDATE leads SET status='sent', sent_at=?, error=NULL WHERE email=?",
            (datetime.now().isoformat(timespec="seconds"), email),
        )
        self.db.commit()

    def mark_failure(self, email, error, permanent=False, max_attempts=3):
        row = self.db.execute("SELECT attempts FROM leads WHERE email=?", (email,)).fetchone()
        attempts = row["attempts"] + 1
        status = "failed" if permanent or attempts >= max_attempts else "queued"
        self.db.execute(
            "UPDATE leads SET status=?, attempts=?, error=? WHERE email=?",
            (status, attempts, str(error)[:300], email),
        )
        self.db.commit()

    def mark_optout(self, email):
        self.db.execute("UPDATE leads SET status='optout' WHERE email=? AND status='queued'", (email.lower(),))
        self.db.commit()

    def sent_today(self) -> int:
        today = datetime.now().strftime("%Y-%m-%d")
        return self.db.execute(
            "SELECT COUNT(*) FROM leads WHERE status='sent' AND sent_at LIKE ?", (today + "%",)
        ).fetchone()[0]

    def counts(self) -> dict:
        rows = self.db.execute("SELECT status, COUNT(*) n FROM leads GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    def known(self, email) -> bool:
        return self.db.execute("SELECT 1 FROM leads WHERE email=?", (email.lower(),)).fetchone() is not None


def read_optout(path: Path) -> set:
    if not path.exists():
        return set()
    return {m.group(0).lower() for m in FIND_RE.finditer(path.read_text(encoding="utf-8"))}


def parse_file(path: Path) -> list:
    """Return [(email, name, company)] from a CSV or plain list of emails.

    Understands a header row with email/name/company columns; otherwise takes
    every email-looking cell. Missing name/company are guessed from the address.
    """
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    header = [c.strip().lower() for c in rows[0]]
    out = []
    if "email" in header or "e-mail" in header:
        idx = {k: header.index(k) for k in ("email", "e-mail", "name", "company") if k in header}
        ecol = idx.get("email", idx.get("e-mail"))
        for r in rows[1:]:
            if ecol >= len(r):
                continue
            email = r[ecol].strip()
            name = r[idx["name"]].strip() if "name" in idx and idx["name"] < len(r) else ""
            company = r[idx["company"]].strip() if "company" in idx and idx["company"] < len(r) else ""
            out.append((email, name, company))
    else:
        for r in rows:
            for cell in r:
                m = FIND_RE.search(cell)
                if m:
                    out.append((m.group(0), "", ""))
    return out


def ingest(store: Store, path: Path, optout: set) -> dict:
    stats = {"added": 0, "duplicate": 0, "invalid": 0, "optout": 0}
    for email, name, company in parse_file(path):
        email = email.strip().lower()
        if not EMAIL_RE.match(email):
            stats["invalid"] += 1
            continue
        if email in optout:
            stats["optout"] += 1
            continue
        name = name or guess_name(email)
        company = company or guess_company(email)
        if store.add(email, name, company, path.name):
            stats["added"] += 1
        else:
            stats["duplicate"] += 1
    return stats
