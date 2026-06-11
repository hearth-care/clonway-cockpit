"""Mail sender identity helpers shared by Clonway workers.

The helpers here are intentionally stdlib-only. Workers keep their own Gmail
OAuth and send/draft clients, but route MIME From formatting through this module
so named personas do not degrade into bare addresses in inbox or draft rows.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from email.utils import formataddr, parseaddr


class MailIdentityError(ValueError):
    """Raised when a sender identity cannot produce a valid email address."""


@dataclass(frozen=True)
class MailIdentity:
    address: str
    display_name: str = ""
    source: str = ""

    def __post_init__(self) -> None:
        parsed_name, parsed_address = parseaddr(self.address)
        if parsed_name or parsed_address != self.address or not _looks_like_email(parsed_address):
            raise MailIdentityError(f"invalid email address: {self.address!r}")


def format_from_header(identity: MailIdentity | str) -> str:
    """Return the MIME From header for a worker sender identity.

    Preformatted headers are preserved. Bare address strings are validated and
    returned unchanged; callers that know an address represents a persona should
    call ``resolve_mail_identity`` first.
    """
    if isinstance(identity, str):
        display_name, address = parseaddr(identity)
        if display_name:
            return identity
        return MailIdentity(address=address or identity).address

    return (
        formataddr((identity.display_name, identity.address))
        if identity.display_name
        else identity.address
    )


def resolve_mail_identity(
    address: str,
    *,
    display_name: str = "",
    resolver: Callable[[str], str | None] | None = None,
    source: str = "",
) -> MailIdentity:
    """Resolve a sender address into a ``MailIdentity``.

    Resolver failures fall back to a bare identity because sender-display
    lookups should not crash an otherwise valid send path. Workers that require
    a name for a specific persona should pin that expectation in their tests.
    """
    parsed_name, parsed_address = parseaddr(address)
    if parsed_name and not display_name:
        display_name = parsed_name
    normalized = parsed_address or address

    resolved_name = display_name
    if not resolved_name and resolver is not None:
        try:
            resolved_name = resolver(normalized) or ""
        except Exception:  # noqa: BLE001 - lookup failures degrade to bare address
            resolved_name = ""

    return MailIdentity(address=normalized, display_name=resolved_name, source=source)


def _looks_like_email(address: str) -> bool:
    local, sep, domain = address.partition("@")
    return bool(local and sep and domain and " " not in address)
