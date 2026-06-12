"""Build operator emails one way — a multipart/alternative builder plus the Gmail ``raw`` encoder.

Stdlib-only. The From header is routed through :func:`clonway_cockpit.mail_identity.format_from_header`
so a named persona never degrades to a bare address, and every message carries a text/plain part
(no html-only emails — the inconsistency that prompted this extraction).
"""

from __future__ import annotations

import base64
from email.message import EmailMessage
from html.parser import HTMLParser

from clonway_cockpit.mail_identity import MailIdentity, format_from_header


def build_message(
    *,
    to: str | list[str],
    sender: MailIdentity | str,
    subject: str,
    html: str,
    plain: str | None = None,
) -> EmailMessage:
    """Return a multipart/alternative :class:`~email.message.EmailMessage` (text + html).

    ``sender`` may be a :class:`~clonway_cockpit.mail_identity.MailIdentity` or a bare/preformatted
    address string; either way it goes through ``format_from_header``. When ``plain`` is omitted a
    stdlib text rendering of ``html`` is used, so the message is never html-only.
    """
    msg = EmailMessage()
    msg["To"] = ", ".join(to) if isinstance(to, (list, tuple)) else to
    msg["From"] = format_from_header(sender)
    msg["Subject"] = subject
    msg.set_content(plain if plain is not None else html_to_text(html))
    msg.add_alternative(html, subtype="html")
    return msg


def to_raw(msg: EmailMessage) -> str:
    """base64url-encode a message for the Gmail API ``users().messages().send`` ``raw`` field."""
    return base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")


class _TextExtractor(HTMLParser):
    """Minimal HTML→text: drops <style>/<script>/<head>, turns block tags into newlines."""

    _DROP = frozenset({"style", "script", "head"})
    _BREAK = frozenset({"br", "p", "div", "tr", "li", "h1", "h2", "h3", "table"})

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._DROP:
            self._drop_depth += 1
        elif tag in self._BREAK:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROP and self._drop_depth:
            self._drop_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self._chunks.append(data)

    @property
    def text(self) -> str:
        return "".join(self._chunks)


def html_to_text(html: str) -> str:
    """Best-effort stdlib HTML→plain-text fallback for the text/plain part.

    Lossy by design — a caller with a real plain-text rendering should pass ``plain`` explicitly.
    Collapses runs of blank lines so the fallback stays readable.
    """
    parser = _TextExtractor()
    parser.feed(html)
    out: list[str] = []
    for line in parser.text.splitlines():
        stripped = line.strip()
        if stripped or (out and out[-1]):
            out.append(stripped)
    return "\n".join(out).strip()
