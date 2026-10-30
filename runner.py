"""One scheduled run: ingest new lists, then send today's batch."""
import logging
import os
import random
import smtplib
import time
from datetime import datetime, timedelta
from email.message import EmailMessage

import mailer
from store import Store, ingest, read_optout

log = logging.getLogger("coldmail")
STALE_LOCK_SEC = 6 * 3600


class Locked(Exception):
    pass


def acquire_lock(path):
    if path.exists() and time.time() - path.stat().st_mtime > STALE_LOCK_SEC:
        path.unlink()
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise Locked("another run is already in progress")
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)


def ingest_inbox(cfg, store, optout, dry_run):
    inbox = cfg["dir"] / "inbox"
    done = inbox / "processed"
    inbox.mkdir(exist_ok=True)
    for path in sorted(p for p in inbox.iterdir() if p.suffix.lower() in (".csv", ".txt")):
        stats = ingest(store, path, optout)
        log.info("Read %s: %s", path.name, stats)
        if not dry_run:
            done.mkdir(exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path.rename(done / f"{stamp}-{path.name}")


def update_optouts(cfg, store, now):
    """Add anyone who replied 'unsubscribe' to optout.txt (best effort)."""
    since = (now - timedelta(days=14)).strftime("%d-%b-%Y")
    try:
        found = mailer.scan_unsubscribes(cfg, since)
    except Exception as e:  # never let this block sending
        log.warning("Unsubscribe check skipped: %s", e)
        return
    path = cfg["dir"] / "optout.txt"
    existing = read_optout(path)
    new = {a for a in found if store.known(a) and a not in existing}
    if new:
        with open(path, "a", encoding="utf-8") as f:
            f.write("".join(a + "\n" for a in sorted(new)))
        for a in new:
            store.mark_optout(a)
        log.info("New opt-outs: %s", ", ".join(sorted(new)))


def summary_mail(cfg, sent, failed, counts):
    msg = EmailMessage()
    msg["From"] = msg["To"] = cfg["GMAIL_ADDRESS"]
    msg["Subject"] = f"[cold-mail:{cfg['profile']}] {sent} sent, {failed} failed, {counts.get('queued', 0)} left"
    msg.set_content(f"Sent today: {sent}\nFailed: {failed}\nTotals: {counts}\n")
    return msg


def run(cfg, dry_run=False, limit=None, force=False,
        sender_factory=mailer.Sender, sleep=time.sleep, now=datetime.now):
    store = Store(cfg["dir"] / "sent.db")
    lock = cfg["dir"] / ".lock"
    acquire_lock(lock)
    try:
        return _run(cfg, store, dry_run, limit, force, sender_factory, sleep, now)
    finally:
        store.db.close()
        lock.unlink(missing_ok=True)


def _run(cfg, store, dry_run, limit, force, sender_factory, sleep, now):
    optout_path = cfg["dir"] / "optout.txt"
    ingest_inbox(cfg, store, read_optout(optout_path), dry_run)

    if not force and not dry_run and not (cfg["start_hour"] <= now().hour < cfg["end_hour"]):
        log.info("Outside sending hours (%d-%d); nothing to do.", cfg["start_hour"], cfg["end_hour"])
        return {"sent": 0, "failed": 0}

    remaining = cfg["daily_limit"] - store.sent_today()
    if limit is not None:
        remaining = min(remaining, limit)
    if remaining <= 0:
        log.info("Daily limit reached (%d). Nothing to do.", cfg["daily_limit"])
        return {"sent": 0, "failed": 0}
    if not store.queued(1):
        log.info("Queue is empty.")
        return {"sent": 0, "failed": 0}

    template = mailer.load_template(cfg["dir"] / "template.txt")
    if not dry_run:
        if not cfg["GMAIL_ADDRESS"] or not cfg["GMAIL_APP_PASSWORD"]:
            raise SystemExit("Set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in the profile's .env")

    optout = read_optout(optout_path)
    sender = None if dry_run else sender_factory(cfg)
    sent = failed = consecutive = 0
    try:
        batch = store.queued(remaining)
        last = batch[-1] if batch else None
        for lead in batch:
            if lead["email"] in optout:
                store.mark_optout(lead["email"])
                continue
            subject, body = mailer.render(template)
            if dry_run:
                print(f"--- To: {lead['email']}")
                print(f"Subject: {subject}\n{body}\n")
                sent += 1
                continue
            msg = mailer.build_message(cfg, lead["email"], subject, body)
            try:
                sender.send(msg)
            except smtplib.SMTPAuthenticationError as e:
                log.error("Gmail login failed - check GMAIL_APP_PASSWORD: %s", e)
                raise SystemExit(2)
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPResponseException) as e:
                code = getattr(e, "smtp_code", 550)
                permanent = isinstance(e, smtplib.SMTPRecipientsRefused) or 500 <= code < 600
                store.mark_failure(lead["email"], e, permanent=permanent)
                failed += 1
                consecutive += 1
                log.warning("Failed %s: %s", lead["email"], e)
            except OSError as e:  # network down/blocked: not the address's fault, so keep it queued
                log.error("Cannot reach Gmail (%s). Stopping; will retry next run.", e)
                break
            except Exception as e:
                store.mark_failure(lead["email"], e)
                failed += 1
                consecutive += 1
                log.warning("Error sending to %s: %s", lead["email"], e)
            else:
                store.mark_sent(lead["email"])
                sent += 1
                consecutive = 0
                log.info("Sent to %s", lead["email"])
            if consecutive >= 3:
                log.error("3 failures in a row; stopping this run.")
                break
            if lead is not last:
                sleep(random.uniform(cfg["min_delay"], cfg["max_delay"]))
        if not dry_run and (sent or failed):
            try:
                sender.send(summary_mail(cfg, store.sent_today(), failed, store.counts()))
            except Exception as e:
                log.warning("Could not send summary: %s", e)
    finally:
        if sender:
            sender.close()
    if not dry_run and sent and cfg["CHECK_UNSUBSCRIBES"] == "1":
        log.info("Checking inbox for unsubscribe replies...")
        update_optouts(cfg, store, now())
    verb = "previewed" if dry_run else "sent"
    log.info("Run finished: %d %s, %d failed. Totals: %s", sent, verb, failed, store.counts())
    return {"sent": sent, "failed": failed}
