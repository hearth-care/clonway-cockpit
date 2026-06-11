from __future__ import annotations

import pytest

from clonway_cockpit.mail_identity import (
    MailIdentity,
    MailIdentityError,
    format_from_header,
    resolve_mail_identity,
)


def test_format_from_header_uses_display_name() -> None:
    identity = MailIdentity(
        address="milo.garth@clonwaycare.co.uk",
        display_name="Milo Garth",
        source="gmail.sendAs",
    )

    assert format_from_header(identity) == "Milo Garth <milo.garth@clonwaycare.co.uk>"


def test_format_from_header_preserves_preformatted_header() -> None:
    header = "Milo Garth <milo.garth@clonwaycare.co.uk>"

    assert format_from_header(header) == header


def test_resolve_mail_identity_uses_resolver_for_bare_address() -> None:
    seen: list[str] = []

    def resolver(address: str) -> str:
        seen.append(address)
        return "Milo Garth"

    identity = resolve_mail_identity(
        "milo.garth@clonwaycare.co.uk",
        resolver=resolver,
        source="gmail.sendAs",
    )

    assert seen == ["milo.garth@clonwaycare.co.uk"]
    assert identity == MailIdentity(
        address="milo.garth@clonwaycare.co.uk",
        display_name="Milo Garth",
        source="gmail.sendAs",
    )


def test_resolve_mail_identity_keeps_explicit_display_name_without_resolver_call() -> None:
    def resolver(_address: str) -> str:
        raise AssertionError("resolver should not be called when display_name is explicit")

    identity = resolve_mail_identity(
        "milo.garth@clonwaycare.co.uk",
        display_name="Milo Garth",
        resolver=resolver,
        source="config",
    )

    assert identity.display_name == "Milo Garth"
    assert identity.source == "config"


def test_resolve_mail_identity_falls_back_to_bare_address_when_resolver_fails() -> None:
    def resolver(_address: str) -> str:
        raise RuntimeError("settings endpoint unavailable")

    identity = resolve_mail_identity(
        "milo.garth@clonwaycare.co.uk",
        resolver=resolver,
        source="gmail.sendAs",
    )

    assert identity == MailIdentity(
        address="milo.garth@clonwaycare.co.uk",
        display_name="",
        source="gmail.sendAs",
    )
    assert format_from_header(identity) == "milo.garth@clonwaycare.co.uk"


def test_invalid_address_fails_before_header_formatting() -> None:
    with pytest.raises(MailIdentityError, match="invalid email address"):
        MailIdentity(address="not an address", display_name="Milo Garth")
