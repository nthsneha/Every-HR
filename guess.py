"""Guess a recipient's first name and company from an email address."""
import re

FREE_PROVIDERS = {
    "gmail", "googlemail", "yahoo", "ymail", "outlook", "hotmail", "live", "msn",
    "icloud", "me", "aol", "proton", "protonmail", "zoho", "rediffmail", "gmx",
    "mail", "yandex",
}
GENERIC_LOCALS = {
    "hr", "careers", "career", "jobs", "job", "info", "contact", "hello", "hi",
    "admin", "support", "team", "recruit", "recruiter", "recruitment", "talent",
    "hiring", "office", "mail", "sales", "enquiry", "inquiry", "help", "people",
    "humanresources", "work", "apply", "resume", "cv", "noreply", "no-reply",
}
SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc"}


def guess_company(email: str) -> str:
    """Company name from the domain, or '' for free mail providers."""
    domain = email.rsplit("@", 1)[-1].lower()
    labels = domain.split(".")
    if len(labels) < 2:
        return ""
    labels = labels[:-1]  # drop the TLD
    if len(labels) > 1 and labels[-1] in SECOND_LEVEL:
        labels = labels[:-1]  # co.in, com.au, ...
    core = labels[-1]
    if core in FREE_PROVIDERS:
        return ""
    return " ".join(w.capitalize() for w in re.split(r"[-_]+", core) if w)


def guess_name(email: str) -> str:
    """First name from the local part, or '' if it looks generic/not a name."""
    local = email.split("@", 1)[0].lower()
    if local in GENERIC_LOCALS:
        return ""
    first = re.split(r"[._\-+0-9]+", local)[0]
    if len(first) < 3 or first in GENERIC_LOCALS or not first.isalpha():
        return ""
    return first.capitalize()
