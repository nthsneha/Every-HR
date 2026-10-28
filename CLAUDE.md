# cold-mail

Python tool (standard library only, Python 3.9+) that sends templated pitch emails from a user's own Gmail, a few a day, from lists dropped into a folder. Built for job/internship self-pitching to HR contacts. Two people use it separately, each with their own profile.

## Layout
- `send.py` CLI: `--profile NAME` then `init | run [--dry-run --limit N --force] | status | schedule [--apply]`
- `runner.py` one run: ingest `inbox/*.csv|txt`, check sending window, send up to daily cap, summary email, then unsubscribe scan
- `mailer.py` template parsing (`## WITH_COMPANY` / `## NO_COMPANY`), message build + resume attachment, Gmail SMTP (tries port 587 then 465), IMAP unsubscribe scan
- `store.py` SQLite queue (`sent.db`), one row per address, so nobody is emailed twice; CSV parsing
- `guess.py` guesses first name and company from the address (free providers and generic locals like hr@ give none)
- `config.py` reads `profiles/NAME/.env`
- `test_coldmail.py` run with `python3 -m unittest test_coldmail`
- `profiles/NAME/` holds `.env` (secrets, never commit), `template.txt`, `optout.txt`, `inbox/`, `inbox/processed/`, `sent.db`, `run.log`

## Behaviour and decisions
- Scheduling is cron (Mac/Linux) or schtasks (Windows), hourly. The tool itself decides whether to send: only between SEND_START_HOUR and SEND_END_HOUR (default 9-18), max DAILY_LIMIT (30), random 45-120s between sends. `--force` skips the hour window.
- Template placeholders: `{greeting}` (Hi Name, / Hi there,), `{name}`, `{company}`. Any other `{...}` crashes rendering. The tool refuses to run while `[EDIT` placeholders remain.
- An unsubscribe line is appended to every email automatically; replies saying unsubscribe are added to `optout.txt` after a run.
- Auth failure stops the run and logs; it cannot email an alert since sending is what broke.

## Lessons from setup
- Port 465 was blocked on one network; 587 fallback added. If sending hangs, suspect network/VPN.
- The inbox scan once hung; it now runs after sending, reads 50 messages, 30s timeout. `CHECK_UNSUBSCRIBES=0` disables it.
- macOS cron cannot read ~/Downloads, ~/Documents or ~/Desktop. Keep the folder at e.g. `~/cold-mail`, then re-run `schedule --apply`.
- Never use placeholder-looking addresses (yourname@gmail.com) in test lists: they are real sends. Test with addresses you control.
- Known weakness: names glued together (rahulverma@) are guessed as one name ("Hi Rahulverma,"). Planned fix: use a first name only when the address has a `.` or `_` separator.

## Not built yet
- Web scraping for HR emails (planned as a separate piece; mind robots.txt and privacy law).
