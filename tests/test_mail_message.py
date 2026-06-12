from __future__ import annotations

import base64

from clonway_cockpit.mail import build_message, html_to_text, to_raw
from clonway_cockpit.mail_identity import MailIdentity


def _content_types(msg) -> set[str]:  # noqa: ANN001 - EmailMessage
    return {part.get_content_type() for part in msg.iter_parts()}


def test_build_message_is_multipart_alternative_with_both_parts() -> None:
    msg = build_message(
        to="ollie.page@clonwaycare.co.uk",
        sender=MailIdentity(address="milo.garth@clonwaycare.co.uk", display_name="Milo Garth"),
        subject="Daily digest",
        html="<p>Hello</p>",
        plain="Hello",
    )

    assert msg.get_content_type() == "multipart/alternative"
    assert _content_types(msg) == {"text/plain", "text/html"}
    assert msg.get_body(preferencelist=("plain",)).get_content().strip() == "Hello"
    assert "Hello" in msg.get_body(preferencelist=("html",)).get_content()


def test_build_message_routes_from_through_mail_identity() -> None:
    msg = build_message(
        to="ollie.page@clonwaycare.co.uk",
        sender=MailIdentity(address="milo.garth@clonwaycare.co.uk", display_name="Milo Garth"),
        subject="x",
        html="<p>x</p>",
    )

    # A named persona must not degrade to a bare address.
    assert msg["From"] == "Milo Garth <milo.garth@clonwaycare.co.uk>"


def test_build_message_accepts_a_bare_sender_string() -> None:
    msg = build_message(
        to="ollie.page@clonwaycare.co.uk",
        sender="milo.garth@clonwaycare.co.uk",
        subject="x",
        html="<p>x</p>",
    )

    assert msg["From"] == "milo.garth@clonwaycare.co.uk"


def test_build_message_joins_multiple_recipients() -> None:
    msg = build_message(
        to=["a@x.co", "b@x.co"],
        sender="milo.garth@clonwaycare.co.uk",
        subject="x",
        html="<p>x</p>",
    )

    assert msg["To"] == "a@x.co, b@x.co"


def test_build_message_synthesises_a_plain_part_when_omitted() -> None:
    # No html-only emails: an omitted plain part is derived from the html.
    msg = build_message(
        to="ollie.page@clonwaycare.co.uk",
        sender="milo.garth@clonwaycare.co.uk",
        subject="x",
        html="<style>p{color:red}</style><p>Hello</p><div>World</div>",
    )

    plain = msg.get_body(preferencelist=("plain",)).get_content()
    assert "Hello" in plain and "World" in plain
    assert "<p>" not in plain and "color:red" not in plain


def test_to_raw_is_base64url_of_the_message() -> None:
    msg = build_message(
        to="ollie.page@clonwaycare.co.uk",
        sender="milo.garth@clonwaycare.co.uk",
        subject="Reconciliation",
        html="<p>x</p>",
    )

    decoded = base64.urlsafe_b64decode(to_raw(msg))
    assert decoded == msg.as_bytes()
    assert b"Subject: Reconciliation" in decoded


def test_html_to_text_strips_markup_and_collapses_blank_runs() -> None:
    text = html_to_text("<h1>Title</h1>\n\n\n<p>Body</p><script>ignore()</script>")

    assert "Title" in text and "Body" in text
    assert "ignore" not in text and "<" not in text
    assert "\n\n\n" not in text
