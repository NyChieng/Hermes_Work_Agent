"""
Gmail integration via IMAP + App Password.

Setup (2 minutes):
  1. Enable 2-step verification on your Google account
  2. Go to myaccount.google.com/apppasswords
  3. Create an App Password for "Mail"
  4. Add to .env:
       GMAIL_ADDRESS=you@gmail.com
       GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
"""

import email as _email_lib
import imaplib
import logging
import os
from email.header import decode_header as _dh

logger = logging.getLogger(__name__)

_IMAP_HOST = "imap.gmail.com"


# ── connection ────────────────────────────────────────────────────────────────

def _connect() -> imaplib.IMAP4_SSL | None:
    addr = os.getenv("GMAIL_ADDRESS", "").strip()
    pwd  = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not addr or not pwd:
        return None
    try:
        m = imaplib.IMAP4_SSL(_IMAP_HOST)
        m.login(addr, pwd)
        return m
    except Exception as exc:
        logger.warning("Gmail login failed: %s", exc)
        return None


def _not_configured() -> str:
    return (
        "Gmail isn't connected yet. "
        "Add GMAIL_ADDRESS and GMAIL_APP_PASSWORD to your .env — "
        "see gmail.py for the 2-minute setup."
    )


# ── header / body helpers ─────────────────────────────────────────────────────

def _str(header: str) -> str:
    parts = _dh(header or "")
    out   = []
    for part, enc in parts:
        if isinstance(part, bytes):
            out.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            out.append(str(part))
    return "".join(out)


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode("utf-8", errors="replace")[:600]
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode("utf-8", errors="replace")[:600]
        except Exception:
            pass
    return ""


def _parse(raw: bytes) -> dict:
    msg = _email_lib.message_from_bytes(raw)
    return {
        "subject": _str(msg.get("Subject", "(no subject)")),
        "from":    _str(msg.get("From", "")),
        "date":    msg.get("Date", ""),
        "preview": _body(msg)[:300],
    }


# ── public tools ──────────────────────────────────────────────────────────────

def get_emails(count: int = 10, folder: str = "INBOX", unread_only: bool = True) -> list[dict] | str:
    """
    Fetch recent emails. unread_only=True returns only unseen messages.
    Returns [{subject, from, date, preview}] or error string.
    """
    m = _connect()
    if not m:
        return _not_configured()
    try:
        m.select(folder)
        criteria = "UNSEEN" if unread_only else "ALL"
        _, data  = m.search(None, criteria)
        ids = data[0].split()
        if not ids:
            return [] if unread_only else "No emails found."
        fetch_ids = ids[-count:]
        results   = []
        for eid in reversed(fetch_ids):
            _, msg_data = m.fetch(eid, "(RFC822)")
            if msg_data and msg_data[0]:
                results.append(_parse(msg_data[0][1]))
        return results
    except Exception as exc:
        logger.warning("get_emails failed: %s", exc)
        return f"Could not read emails: {exc}"
    finally:
        try: m.logout()
        except Exception: pass


def search_emails(query: str, count: int = 10) -> list[dict] | str:
    """
    Search Gmail for emails containing a keyword in subject or body.
    Returns [{subject, from, date, preview}] or error string.
    """
    m = _connect()
    if not m:
        return _not_configured()
    try:
        m.select("INBOX")
        # Try subject first, then body
        _, data = m.search(None, f'SUBJECT "{query}"')
        ids = data[0].split()
        if not ids:
            _, data = m.search(None, f'TEXT "{query}"')
            ids = data[0].split()
        if not ids:
            return f"No emails found matching '{query}'."
        fetch_ids = ids[-count:]
        results   = []
        for eid in reversed(fetch_ids):
            _, msg_data = m.fetch(eid, "(RFC822)")
            if msg_data and msg_data[0]:
                results.append(_parse(msg_data[0][1]))
        return results
    except Exception as exc:
        logger.warning("search_emails failed: %s", exc)
        return f"Email search failed: {exc}"
    finally:
        try: m.logout()
        except Exception: pass
