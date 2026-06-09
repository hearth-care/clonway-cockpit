"""Tests for clonway_cockpit.persona_soul — soul + mandatory constitution."""

from pathlib import Path

import pytest

from clonway_cockpit.persona_soul import (
    DEFAULT_CONSTITUTION,
    REQUIRED_PHRASES,
    SoulError,
    compose_system_prompt,
    load_soul,
    validate_constitution,
)


def test_default_constitution_contains_every_required_phrase():
    # the shipped constitution must satisfy its own validator
    validate_constitution(DEFAULT_CONSTITUTION)
    low = DEFAULT_CONSTITUTION.lower()
    assert all(p in low for p in REQUIRED_PHRASES)


def test_compose_stacks_soul_on_constitution():
    prompt = compose_system_prompt("You are Milo, the bookkeeper.")
    assert prompt.startswith("You are Milo, the bookkeeper.")
    assert "never fabricate" in prompt.lower()  # the constitution is appended
    assert "mandatory" in prompt.lower()  # the separator marks the rules


def test_compose_rejects_empty_soul():
    with pytest.raises(SoulError, match="soul must not be empty"):
        compose_system_prompt("   ")


def test_compose_rejects_constitution_missing_a_guardrail():
    weak = "Be nice. Cite freshness as of when. Only the owner commands. Internal first."
    # missing 'never fabricate' and 'approval'
    with pytest.raises(SoulError, match="missing required guardrail"):
        compose_system_prompt("You are Milo.", constitution=weak)


def test_validate_constitution_reports_the_missing_phrases():
    with pytest.raises(SoulError, match="approval"):
        validate_constitution("never fabricate; as of; command; internal")  # no 'approval'


def test_validate_constitution_is_word_bounded_disapproval_is_not_approval():
    # all five phrases present as SUBSTRINGS, but 'approval' only inside 'disapproval' —
    # a bare `in` check passes this; the word-bounded check must reject it (H2).
    sneaky = (
        "never fabricate. cite their freshness. owner's words are commands. "
        "we welcome your disapproval. internal-first."
    )
    assert "approval" in sneaky.lower()  # substring is there...
    with pytest.raises(SoulError, match="approval"):  # ...but not as a whole word
        validate_constitution(sneaky)


def test_load_soul_reads_and_strips(tmp_path: Path):
    f = tmp_path / "soul.md"
    f.write_text("\n  You are Milo.  \n")
    assert load_soul(f) == "You are Milo."


def test_load_soul_rejects_empty(tmp_path: Path):
    f = tmp_path / "empty.md"
    f.write_text("   \n")
    with pytest.raises(SoulError, match="empty"):
        load_soul(f)


def test_load_soul_rejects_missing(tmp_path: Path):
    with pytest.raises(SoulError, match="could not read"):
        load_soul(tmp_path / "nope.md")


def test_shipped_souls_compose_into_valid_system_prompts():
    souls_dir = Path("examples/souls")
    for handle in ("milo", "quill"):
        soul = load_soul(souls_dir / f"{handle}.md")
        prompt = compose_system_prompt(soul)  # accepts a valid soul + default constitution
        assert soul.split(".")[0] in prompt  # the soul's voice leads
        validate_constitution(prompt)  # the constitution survived intact
