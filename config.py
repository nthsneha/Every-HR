"""Profile folders and their .env settings."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROFILES = ROOT / "profiles"

DEFAULTS = {
    "GMAIL_ADDRESS": "",
    "GMAIL_APP_PASSWORD": "",
    "SENDER_NAME": "",
    "RESUME_PATH": "",          # optional attachment (resume / portfolio PDF)
    "DAILY_LIMIT": "30",
    "MIN_DELAY_SEC": "45",
    "MAX_DELAY_SEC": "120",
    "SEND_START_HOUR": "9",     # only send between these local hours
    "SEND_END_HOUR": "18",
    "CHECK_UNSUBSCRIBES": "1",  # scan the Gmail inbox for "unsubscribe" replies
}


def read_env(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def load(profile: str) -> dict:
    pdir = PROFILES / profile
    if not pdir.is_dir():
        raise SystemExit(f"No profile '{profile}'. Create it with: python send.py --profile {profile} init")
    cfg = dict(DEFAULTS)
    cfg.update(read_env(pdir / ".env"))
    cfg["dir"] = pdir
    cfg["profile"] = profile
    cfg["daily_limit"] = int(cfg["DAILY_LIMIT"])
    cfg["min_delay"] = float(cfg["MIN_DELAY_SEC"])
    cfg["max_delay"] = float(cfg["MAX_DELAY_SEC"])
    cfg["start_hour"] = int(cfg["SEND_START_HOUR"])
    cfg["end_hour"] = int(cfg["SEND_END_HOUR"])
    return cfg


def list_profiles() -> list:
    return sorted(p.name for p in PROFILES.iterdir() if p.is_dir()) if PROFILES.exists() else []
