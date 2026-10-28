#!/usr/bin/env python3
"""Cold-mail tool. Usage: python send.py --profile NAME {init,run,status,schedule}"""
import argparse
import logging
import platform
import shlex
import subprocess
import sys
from pathlib import Path

import config
import runner

SAMPLE_ENV = """# Gmail needs 2-step verification on, then an App Password:
# https://myaccount.google.com/apppasswords
GMAIL_ADDRESS=you@gmail.com
GMAIL_APP_PASSWORD=
SENDER_NAME=Your Name
# Optional attachment (file in this folder, or a full path)
RESUME_PATH=
DAILY_LIMIT=30
MIN_DELAY_SEC=45
MAX_DELAY_SEC=120
SEND_START_HOUR=9
SEND_END_HOUR=18
"""

SAMPLE_TEMPLATE = """# Placeholders: {greeting}  {name}  {company}
# Remove every [EDIT ...] line before sending - the tool refuses to run until you do.

## WITH_COMPANY
Subject: [EDIT: subject that mentions {company}]

{greeting}

[EDIT: 3-5 sentences pitching yourself, mentioning {company}.]

[EDIT: your name, phone/LinkedIn]

## NO_COMPANY
Subject: [EDIT: subject without a company name]

{greeting}

[EDIT: 3-5 sentences pitching yourself, with no company name.]

[EDIT: your name, phone/LinkedIn]
"""


def resolve_profile(name):
    if name:
        return name
    found = config.list_profiles()
    if len(found) == 1:
        return found[0]
    raise SystemExit("Pass --profile NAME. Existing profiles: " + (", ".join(found) or "none"))


def cmd_init(name):
    pdir = config.PROFILES / name
    if pdir.exists():
        raise SystemExit(f"Profile '{name}' already exists at {pdir}")
    (pdir / "inbox").mkdir(parents=True)
    (pdir / ".env").write_text(SAMPLE_ENV, encoding="utf-8")
    (pdir / "template.txt").write_text(SAMPLE_TEMPLATE, encoding="utf-8")
    (pdir / "optout.txt").write_text("", encoding="utf-8")
    print(f"Created {pdir}\nNext: edit .env and template.txt there, then drop CSV lists into {pdir / 'inbox'}")


def cmd_status(cfg):
    from store import Store
    s = Store(cfg["dir"] / "sent.db")
    print(f"Profile {cfg['profile']}: sent today {s.sent_today()}/{cfg['daily_limit']}, totals {s.counts()}")


def schedule_command(profile):
    """Command that runs hourly; the tool itself decides whether to send."""
    py = sys.executable
    script = str(Path(__file__).resolve())
    if platform.system() == "Windows":
        task = f'"{py}" "{script}" --profile {profile} run'
        return ["schtasks", "/Create", "/F", "/SC", "HOURLY", "/TN", f"ColdMail-{profile}", "/TR", task]
    line = f"0 * * * * {shlex.quote(py)} {shlex.quote(script)} --profile {shlex.quote(profile)} run >/dev/null 2>&1"
    return line


def cmd_schedule(profile, apply):
    cmd = schedule_command(profile)
    if isinstance(cmd, list):
        print("Command:", " ".join(cmd))
        if apply:
            subprocess.run(cmd, check=True)
        return
    marker = f"--profile {shlex.quote(profile)} run"
    print("Cron line:", cmd)
    if apply:
        current = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout
        kept = [l for l in current.splitlines() if marker not in l]
        subprocess.run(["crontab", "-"], input="\n".join(kept + [cmd]) + "\n", text=True, check=True)
        print("Installed.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", help="profile name (folder under profiles/)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init", help="create a new profile folder")
    r = sub.add_parser("run", help="ingest the inbox and send today's batch")
    r.add_argument("--dry-run", action="store_true", help="preview emails, send nothing")
    r.add_argument("--limit", type=int, help="send at most N this run")
    r.add_argument("--force", action="store_true", help="ignore the sending-hours window")
    sub.add_parser("status", help="show counts")
    s = sub.add_parser("schedule", help="run automatically every hour")
    s.add_argument("--apply", action="store_true", help="actually install it (default just prints)")
    args = ap.parse_args()

    if args.cmd == "init":
        if not args.profile:
            raise SystemExit("Usage: python send.py --profile NAME init")
        return cmd_init(args.profile)
    cfg = config.load(resolve_profile(args.profile))
    if args.cmd == "status":
        return cmd_status(cfg)
    if args.cmd == "schedule":
        return cmd_schedule(cfg["profile"], args.apply)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(message)s",
        handlers=[logging.FileHandler(cfg["dir"] / "run.log", encoding="utf-8"), logging.StreamHandler()],
    )
    try:
        runner.run(cfg, dry_run=args.dry_run, limit=args.limit, force=args.force)
    except runner.Locked as e:
        logging.getLogger("coldmail").info("Skipped: %s", e)
    except mailer_error() as e:
        raise SystemExit(str(e))


def mailer_error():
    import mailer
    return mailer.TemplateError


if __name__ == "__main__":
    main()
