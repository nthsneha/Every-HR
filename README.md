# cold-mail

Sends your pitch emails from your own Gmail, a few a day, automatically. Needs Python 3.9+ and nothing else. On Windows use `python` instead of `python3`.

## Setup (once)
1. Turn on 2-step verification in Google, then create an App Password: https://myaccount.google.com/apppasswords
2. Keep this folder in your home folder (e.g. `~/cold-mail`), NOT in Downloads, Desktop or Documents (macOS blocks background jobs there).
3. `python3 send.py --profile NAME init`
4. Fill in `profiles/NAME/.env` (Gmail address, app password, your name, optional `RESUME_PATH=resume.pdf` with the file in the same folder).
5. Write your one pitch in `profiles/NAME/template.txt`: first line `Subject: ...`, then the email. Every email starts with `{greeting}`, which becomes "Dear Hiring Team,". Remove every `[EDIT ...]` line.
6. Preview, then install the schedule:
   ```
   python3 send.py --profile NAME run --dry-run
   python3 send.py --profile NAME schedule --apply
   ```

## Daily use
Drop a CSV into `profiles/NAME/inbox/` (first line `email`, then one address per line; extra columns are ignored). Done. Each hour it checks, and between 9:00 and 18:00 it sends up to 30 a day, 45-120 s apart. The computer must be awake for about 30-50 minutes once a day. You get a summary email after each batch.

## Commands
| What | Command |
|---|---|
| Preview emails (sends nothing) | `python3 send.py --profile NAME run --dry-run` |
| Send now (ignore the 9-18 window) | `python3 send.py --profile NAME run --force` |
| Send only 2 now (testing) | `python3 send.py --profile NAME run --force --limit 2` |
| Counts: sent today, queued, failed | `python3 send.py --profile NAME status` |
| See what happened | `tail -20 profiles/NAME/run.log` |
| Install / refresh schedule | `python3 send.py --profile NAME schedule --apply` |
| Check schedule is installed | `crontab -l` |
| Stop the schedule | `crontab -e` and delete the line |
| Run the tests | `python3 -m unittest test_coldmail` |

## Before you send (cautions)
- Test only with addresses you own. Placeholder-looking addresses (like `yourname@gmail.com`) are real sends.
- Each address is emailed once, ever. Deleting `profiles/NAME/sent.db` forgets that history, so only do it while testing.
- Start with ~10 addresses, then grow. Keep `DAILY_LIMIT` at 30 or lower; Gmail flags big cold-mail bursts.
- Never share or commit `.env`. To stop emailing someone, add their address to `optout.txt`.

## Problems and fixes
| You see | Meaning | Fix |
|---|---|---|
| `Outside sending hours` | Not between 9:00 and 18:00 | Wait, or add `--force`, or change `SEND_START_HOUR` / `SEND_END_HOUR` in `.env` |
| `Queue is empty` | No new list, or all already sent | `ls profiles/NAME/inbox` should show a `.csv`/`.txt`; check `status` |
| `Daily limit reached` | 30 sent today | Wait until tomorrow |
| `Gmail login failed` | Wrong app password | Create a new one, paste it in `.env` with no quotes; 2-step verification must be on (work/school accounts may block app passwords) |
| `Could not reach Gmail` | Network blocks mail ports | Turn off VPN; try phone hotspot |
| Command hangs | Slow Gmail/network | `Ctrl+C` is safe (progress is saved). Add `CHECK_UNSUBSCRIBES=0` to `.env` |
| `still contains [EDIT ...]` | Template unfinished | Finish both sections in `template.txt` |
| `KeyError` mentioning a word in `{}` | Unknown placeholder | The only placeholder is `{greeting}` |
| `FileNotFoundError` for the resume | Wrong `RESUME_PATH` | Put the PDF in `profiles/NAME/` and set `RESUME_PATH=resume.pdf` (exact name) |
| `another run is already in progress` | A run is active or crashed | Wait a few minutes; if stuck: `rm profiles/NAME/.lock` |
| Nothing sends by itself | Schedule not firing | `crontab -l` shows a line? Folder not in Downloads/Desktop/Documents? Mac awake in 9-18? After moving the folder, re-run `schedule --apply` |
| Emails land in spam | Gmail distrusts the burst | Lower `DAILY_LIMIT`, vary wording, send to fewer people for a week |
| Gmail says suspicious activity | Sending too much | Stop for a day, lower `DAILY_LIMIT`, then resume |
| Some rows `failed` | Bad or refused address | `status` shows count; details in `run.log`; fix the address and re-add in a new CSV after removing it from the old list |
