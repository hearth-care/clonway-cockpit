"""Shared operator-email composition for Clonway workers.

Stdlib-only by design — the same contract as :mod:`clonway_cockpit.mail_identity`: this package
*composes* the message and *brands* it, but every worker keeps its own Gmail OAuth + send client
(which legitimately diverges by deployment — keyring / file token / Secret Manager). Before this
package, xbook, xquill and xops each re-implemented MIME assembly and the header/footer branding
three different ways; this collapses the duplicated parts to one definition.

A worker's send path becomes::

    from clonway_cockpit.mail import build_message, to_raw, wrap, breadcrumb
    html = wrap(body_html, eyebrow=..., tenant=..., subtitle=..., worker="xbook",
                product="Daily digest", date=today)
    msg = build_message(to=recips, sender=identity, subject=subject, html=html, plain=plain)
    service.users().messages().send(userId="me", body={"raw": to_raw(msg)})   # worker-owned
"""

from __future__ import annotations

from clonway_cockpit.mail.message import build_message, html_to_text, to_raw
from clonway_cockpit.mail.shell import (
    BADGE_COLOURS,
    badge,
    breadcrumb,
    section_eyebrow,
    status_strip,
    wrap,
)

__all__ = [
    "BADGE_COLOURS",
    "badge",
    "breadcrumb",
    "build_message",
    "html_to_text",
    "section_eyebrow",
    "status_strip",
    "to_raw",
    "wrap",
]
