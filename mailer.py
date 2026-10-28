"""Templates, message building, Gmail SMTP sending and unsubscribe scanning."""
import email as emaillib
import imaplib
import mimetypes
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from pathlib import Path


FOOTER = "\n\n--\nNot relevant to you? Just reply \"unsubscribe\" and I won't email you again."
UNSUB_WORDS = re.compile(r"\b(unsubscribe|remove me|stop emailing|do not contact|don'?t contact)\b", re.I)


class TemplateError(Exception):
    pass


def load_templates(path: Path) -> dict:
    """template.txt has two sections: '## WITH_COMPANY' and '## NO_COMPANY'.
    Each begins with a 'Subject:' line, then the body."""
    text = path.read_text(encoding="utf-8")
    if "[EDIT" in text:
        raise TemplateError(f"{path} still contains [EDIT ...] placeholders. Write your pitch first.")
    parts = re.split(r"^##\s*(WITH_COMPANY|NO_COMPANY)\s*$", text, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    if set(sections) != {"WITH_COMPANY", "NO_COMPANY"}:
        raise TemplateError("template.txt needs both '## WITH_COMPANY' and '## NO_COMPANY' sections.")
    out = {}
    for key, block in sections.items():
        first, _, body = block.partition("\n")
        if not first.lower().startswith("subject:"):
            raise TemplateError(f"Section {key} must start with a 'Subject:' line.")
        out[key] = (first.split(":", 1)[1].strip(), body.strip())
    return out


def render(templates: dict, lead) -> tuple:
    name, company = (lead["name"] or "").strip(), (lead["company"] or "").strip()
    subject, body = templates["WITH_COMPANY" if company else "NO_COMPANY"]
    fields = {
        "name": name,
        "company": company,
        "greeting": f"Hi {name}," if name else "Hi there,",
    }
    return subject.format(**fields), body.format(**fields)


def build_message(cfg: dict, to: str, subject: str, body: str, attach: bool = True) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((cfg["SENDER_NAME"], cfg["GMAIL_ADDRESS"]))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body + FOOTER)
    resume = cfg["RESUME_PATH"]
    if attach and resume:
        p = Path(resume).expanduser()
        if not p.is_absolute():
            p = cfg["dir"] / p
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        maintype, _, subtype = ctype.partition("/")
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    return msg


class Sender:
    """One Gmail SMTP connection, reconnecting if Gmail drops it."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.smtp = None

    def _connect(self):
        """Try port 587 (STARTTLS) first, then 465 (SSL); some networks block one of them."""
        ctx = ssl.create_default_context()
        last = None
        for port in (587, 465):
            try:
                if port == 587:
                    smtp = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)
                    smtp.ehlo()
                    smtp.starttls(context=ctx)
                    smtp.ehlo()
                else:
                    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=20)
            except OSError as e:
                last = e
                continue
            smtp.login(self.cfg["GMAIL_ADDRESS"], self.cfg["GMAIL_APP_PASSWORD"])
            self.smtp = smtp
            return
        raise ConnectionError(f"Could not reach Gmail on port 587 or 465 ({last}). Check your network/VPN.")

    def send(self, msg: EmailMessage):
        if self.smtp is None:
            self._connect()
        try:
            self.smtp.send_message(msg)
        except smtplib.SMTPServerDisconnected:
            self._connect()
            self.smtp.send_message(msg)

    def close(self):
        if self.smtp:
            try:
                self.smtp.quit()
            except Exception:
                pass
            self.smtp = None


def _text_of(msg) -> str:
    chunks = []
    for part in msg.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if payload:
                chunks.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(chunks)


def is_unsubscribe(raw_message: bytes) -> str:
    """Return the sender's address if this reply asks to stop, else ''."""
    msg = emaillib.message_from_bytes(raw_message)
    sender = parseaddr(msg.get("From", ""))[1].lower()
    # only the reply itself, not the quoted original that contains our own footer
    lines = []
    for line in _text_of(msg).splitlines():
        if line.startswith(">") or line.lower().startswith("on ") and "wrote" in line.lower():
            break
        lines.append(line)
    if sender and UNSUB_WORDS.search(msg.get("Subject", "") + "\n" + "\n".join(lines)):
        return sender
    return ""


def scan_unsubscribes(cfg: dict, since: str = None) -> set:
    """Read recent inbox mail over IMAP; return addresses that asked to stop."""
    found = set()
    imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    try:
        imap.login(cfg["GMAIL_ADDRESS"], cfg["GMAIL_APP_PASSWORD"])
        imap.select("INBOX", readonly=True)
        _, data = imap.search(None, "SINCE", since or "01-Jan-2000")
        for num in data[0].split()[-50:]:
            _, fetched = imap.fetch(num, "(BODY.PEEK[])")
            addr = is_unsubscribe(fetched[0][1])
            if addr:
                found.add(addr)
    finally:
        try:
            imap.logout()
        except Exception:
            pass
    return found
