"""Drop a markdown draft + xlsx attachment into the user's Gmail Drafts folder.

Uses IMAP with the GMAIL_APP_PASSWORD from .env. Recipient is left blank for
the user to fill in before sending. Subject is auto-extracted from the draft's
"Subject:" line if present, otherwise from the H1.

Usage:
    python -m scripts.draft_to_gmail <draft.md> [<attachment.xlsx>]
"""
from __future__ import annotations

import email.utils
import imaplib
import os
import re
import sys
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import markdown
from dotenv import load_dotenv

REPO = Path(__file__).resolve().parent.parent
load_dotenv(REPO / ".env")


def extract_subject_and_body(md_text: str) -> tuple[str, str]:
    """Pull a Subject line from the draft if present, strip header-style lines
    (To:, Subject:) from the body so the email body is clean."""
    subject = "Sales Cycle Kickoff"
    body_lines = []
    for line in md_text.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("subject:"):
            subject = stripped.split(":", 1)[1].strip()
            continue
        if stripped.lower().startswith("to:"):
            continue
        body_lines.append(line)
    body = "\n".join(body_lines)
    # Trim leading blanks
    body = re.sub(r"^\n+", "", body)
    return subject, body


_TABLE_STYLE = (
    "border-collapse: collapse; border-spacing: 0; "
    "font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; "
    "font-size: 13px; margin: 4px 0 10px 0;"
)
# Cell borders alone form the outer outline — no separate table border, which
# was rendering as a dark "blank row" line above tables in Gmail when
# border-collapse wasn't fully honored.
_TH_STYLE = (
    "background: #1F4E78; color: #ffffff; padding: 6px 10px; "
    "border: 1px solid #d4d4d4; font-weight: 600; white-space: nowrap;"
)
_TD_STYLE = (
    "padding: 5px 10px; border: 1px solid #d4d4d4; vertical-align: top;"
)
_P_STYLE = "margin: 0.4em 0;"
_H1_STYLE = "margin: 0.8em 0 0.3em 0; font-size: 22px;"
_H2_STYLE = "margin: 1.0em 0 0.3em 0; font-size: 17px;"
_H3_STYLE = "margin: 0.8em 0 0.2em 0; font-size: 15px;"
_BODY_WRAPPER_OPEN = (
    '<div style="font-family: -apple-system, BlinkMacSystemFont, \'Segoe UI\', '
    'Helvetica, Arial, sans-serif; font-size: 14px; line-height: 1.45; '
    'color: #222; max-width: 920px;">'
)
_BODY_WRAPPER_CLOSE = "</div>"


def _inject_style(tag_match: "re.Match", base_style: str) -> str:
    tag = tag_match.group(1)  # 'th' or 'td'
    attrs = tag_match.group(2)  # everything between tag name and '>'
    if "style=" in attrs:
        # Prepend our base style inside the existing style attribute so any
        # markdown-emitted alignment (text-align: right;) wins on conflict.
        attrs = re.sub(r'style="', f'style="{base_style} ', attrs, count=1)
    else:
        attrs = f' style="{base_style}"' + attrs
    return f"<{tag}{attrs}>"


def _stylize_html(html: str) -> str:
    """Inject inline styles so Gmail renders tables + tight spacing correctly.

    Gmail strips <style> blocks but preserves inline style="..." attributes,
    so everything has to be on the element itself.
    """
    # Tables: collapsed borders + cellspacing/cellpadding=0 attrs as belt-and-
    # suspenders against legacy email renderers that ignore CSS border-collapse.
    html = html.replace(
        "<table>",
        f'<table cellspacing="0" cellpadding="0" style="{_TABLE_STYLE}">',
    )
    # IMPORTANT: require whitespace OR immediate '>' after the tag name. Without
    # this, `<thead>` matches `<th` + `ead` and gets corrupted into
    # `<th style="..."ead>`, which Gmail renders as a phantom blue cell in the
    # top-left of every table (the "overhang"/"blank row" bug, seen 2026-05-06).
    html = re.sub(r"<(th)(\s[^>]*|)>", lambda m: _inject_style(m, _TH_STYLE), html)
    html = re.sub(r"<(td)(\s[^>]*|)>", lambda m: _inject_style(m, _TD_STYLE), html)

    # Paragraphs and headings: tighten default margins so there's no phantom
    # "blank row" between body text and the table that follows it.
    html = html.replace("<p>", f'<p style="{_P_STYLE}">')
    html = html.replace("<h1>", f'<h1 style="{_H1_STYLE}">')
    html = html.replace("<h2>", f'<h2 style="{_H2_STYLE}">')
    html = html.replace("<h3>", f'<h3 style="{_H3_STYLE}">')

    return html


def md_to_html(body_md: str) -> str:
    """HTML rendering with inline styles for Gmail-friendly tables + spacing."""
    raw = markdown.markdown(body_md, extensions=["tables", "sane_lists"])
    styled = _stylize_html(raw)
    return f"{_BODY_WRAPPER_OPEN}{styled}{_BODY_WRAPPER_CLOSE}"


def build_message(
    subject: str,
    body_md: str,
    body_html: str,
    sender: str,
    attachments: list[Path] | None = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("mixed")
    msg["From"] = sender
    msg["To"] = ""  # blank — user fills in before sending
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid(domain=sender.split("@")[-1])

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(body_md, "plain", "utf-8"))
    alt.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(alt)

    for path in attachments or []:
        with open(path, "rb") as f:
            data = f.read()
        part = MIMEBase("application", "octet-stream")
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition", f'attachment; filename="{path.name}"'
        )
        msg.attach(part)

    return msg


def _delete_drafts_with_subject(M: imaplib.IMAP4_SSL, subject: str) -> int:
    """Move any existing draft whose subject contains all ASCII-safe word tokens
    from this subject (3+ chars, max 6 tokens). Multi-token AND-search avoids
    IMAP's ASCII-only quirk on SUBJECT — single substrings break when the actual
    subject has em-dashes (the search string has spaces where they were)."""
    M.select('"[Gmail]/Drafts"')
    # Strip non-ASCII, split on whitespace, keep only meaningful tokens
    ascii_only = "".join(c if ord(c) < 128 else " " for c in subject)
    tokens = [t for t in ascii_only.split() if len(t) >= 3]
    if not tokens:
        return 0
    # Limit to first 6 to keep the IMAP command short; AND them all
    tokens = tokens[:6]
    criteria: list = []
    for t in tokens:
        safe = t.replace("\\", "\\\\").replace('"', '\\"')
        criteria.extend(["SUBJECT", f'"{safe}"'])
    typ, data = M.search(None, *criteria)
    if typ != "OK" or not data or not data[0]:
        return 0
    nums = data[0].split()
    if not nums:
        return 0
    for num in nums:
        M.store(num, "+FLAGS", "\\Deleted")
    M.expunge()
    return len(nums)


def append_to_drafts(
    msg_bytes: bytes, gmail_user: str, gmail_app_pw: str,
    *, subject_for_replace: str | None = None,
) -> None:
    with imaplib.IMAP4_SSL("imap.gmail.com") as M:
        M.login(gmail_user, gmail_app_pw)
        if subject_for_replace:
            removed = _delete_drafts_with_subject(M, subject_for_replace)
            if removed:
                print(f"  Replaced {removed} existing draft(s) with the same subject.")
        result, _ = M.append(
            '"[Gmail]/Drafts"',
            "\\Draft",
            imaplib.Time2Internaldate(time.time()),
            msg_bytes,
        )
        if result != "OK":
            raise RuntimeError(f"IMAP APPEND failed: {result}")


def upload(draft_path: Path, attachments: list[Path]) -> None:
    user = os.environ["GMAIL_USER"]
    pw = os.environ["GMAIL_APP_PASSWORD"]

    md_text = draft_path.read_text(encoding="utf-8")
    subject, body_md = extract_subject_and_body(md_text)
    body_html = md_to_html(body_md)
    msg = build_message(subject, body_md, body_html, user, attachments)
    append_to_drafts(msg.as_bytes(), user, pw, subject_for_replace=subject)
    print(f"Uploaded draft to Gmail Drafts.")
    print(f"  Subject: {subject}")
    print(f"  Body source: {draft_path.name}")
    if attachments:
        for a in attachments:
            print(f"  Attached: {a.name} ({a.stat().st_size:,} bytes)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.draft_to_gmail <draft.md> [<attachment>...]")
        sys.exit(1)
    draft = Path(sys.argv[1])
    if not draft.exists():
        print(f"Draft not found: {draft}")
        sys.exit(1)
    attachments = [Path(a) for a in sys.argv[2:]]
    for a in attachments:
        if not a.exists():
            print(f"Attachment not found: {a}")
            sys.exit(1)
    upload(draft, attachments)


if __name__ == "__main__":
    main()
