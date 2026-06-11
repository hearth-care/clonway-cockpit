# Platform Mail Identity Contract

**Date:** 2026-06-11
**Repo:** `clonway-cockpit`
**Status:** proposed design -> planning PR

## Goal

Make sender identity a fleet-level invariant: any worker that sends or drafts email must render a
named `From` header such as `Milo Garth <milo.garth@clonwaycare.co.uk>` when a named persona or
send-as alias is configured. A bare address like `milo.garth@clonwaycare.co.uk` must be treated as
an incomplete sender identity unless the worker explicitly marks that as intentional.

The immediate bug came from Auto-Secretary: Gmail had a verified `Milo Garth` send-as alias, but
the digest code built MIME with only the bare address, so Gmail displayed `milo.garth` in inbox and
draft rows. The fix should not remain a one-off xquill lesson.

## Context

`clonway-cockpit` is the shared framework spine for worker protocol, persona metadata, generated
worker scaffolding, and safety contracts. It is not currently an email sender, and its core
dependency set is intentionally small (`rich` only).

The fleet has mixed email postures:

- Auto-Secretary (`xquill`) sends self-addressed summaries and creates fallback drafts through a
  local Gmail client. It now resolves Gmail send-as display names before building the MIME `From`.
- Auto-Bookkeeper (`xbook`) has a live `gmail.send` digest path and some Gmail draft creation.
- Auto-Orchestrator (`xops`) has a live daily digest path in Cloud Run with a `gmail.send` token.
- Auto-Marketer (`xletter`), Auto-Inspector (`xcqc`), and Auto-Admissions create drafts only or
  explicitly forbid `gmail.send`.
- Auto-HR is read-only for Gmail in the current safety posture.
- Auto-Procurer has outreach email MIME construction in its source tree.

That spread matters: a platform rule cannot assume every worker may use `gmail.send`, and it should
not pull Google client libraries into `clonway-cockpit` core. The platform can own the contract and
the pure MIME identity helper; workers keep their own OAuth scopes and provider clients.

## Recommendation

Add a stdlib-only `clonway_cockpit.mail_identity` module plus worker-template guardrails. It should
define the sender identity shape, format the MIME `From` header, and provide tests that new workers
inherit. Existing sender repos migrate to it one by one.

`clonway-cockpit` should not own Gmail sending, Gmail OAuth, or Workspace send-as lookup. Those stay
inside each worker because the permission models differ. For Gmail, a worker may pass a resolver
function that fetches `users.settings.sendAs.get(...).displayName` using its existing service and
scope. The platform helper only consumes the resolved identity and formats it consistently.

## Design

### Sender Identity

Add a small immutable value object:

```python
@dataclass(frozen=True)
class MailIdentity:
    address: str
    display_name: str = ""
    source: str = ""  # e.g. "config", "gmail.sendAs", "persona"
```

Rules:

- `address` must parse as a non-empty email address.
- `display_name`, when present, is used with `email.utils.formataddr`.
- If `display_name` is empty and the address is known to represent a persona or send-as alias, the
  caller should either resolve it or explicitly choose a bare identity.
- `source` is diagnostic only; it should appear in logs/tests, not in the MIME header.

### Formatting API

Core functions:

```python
def format_from_header(identity: MailIdentity | str) -> str: ...

def resolve_mail_identity(
    address: str,
    *,
    display_name: str = "",
    resolver: Callable[[str], str | None] | None = None,
    source: str = "",
) -> MailIdentity: ...
```

Behavior:

- If the caller passes `MailIdentity("milo.garth@...", "Milo Garth")`, the result is
  `Milo Garth <milo.garth@...>`.
- If the caller passes a preformatted header (`"Milo Garth <milo.garth@...>"`), preserve it.
- If a resolver is provided, call it for bare addresses and use the returned display name when
  non-empty.
- If resolution fails, return a bare identity rather than crashing a send path. The caller's tests
  decide whether that fallback is acceptable.

### Worker Template Guardrail

Generated workers should get a safety test that scans live source files for direct MIME email
construction and direct Gmail send/draft calls. The test should fail with a clear message unless
the worker routes mail through its local approved adapter, which in turn uses
`clonway_cockpit.mail_identity`.

This mirrors existing safety tests in the fleet:

- xletter forbids `gmail.send`.
- xcqc is compose-only.
- xhr forbids Gmail write scopes.

The new template guard is not "every worker must send mail". It is "if this worker sends or drafts
mail, the sender identity formatting must go through the platform helper".

### Existing Worker Migration

Migrate live sender repos after the spec is approved:

1. `xops`: daily digest sender, because it is live Cloud Run and already had a Gmail-scope incident.
2. `xbook`: digest sender and draft creation paths.
3. `xsource`: outreach MIME client, with attention to no-send/preflight guardrails.
4. `xletter`, `xcqc`, and `xadmissions`: draft-only adapters can adopt the same `From` formatter
   without enabling `gmail.send`.
5. `xquill`: already fixed locally; later replace its private helper with the shared one.

Each migration PR should include:

- a regression test for named `From` output;
- a fallback test for failed display-name resolution;
- confirmation that the repo's existing send/draft safety posture is unchanged.

### Runtime Verification

For live senders, a unit test is not enough. Each worker that sends production email should have a
safe smoke path that sends a self-addressed or operator-addressed test message and reads it back
from Gmail, checking the received `From` header. Auto-Secretary's proof used exactly that loop:
send with the Milo alias, then read the delivered message back and verify
`From: Milo Garth <milo.garth@clonwaycare.co.uk>`.

For draft-only workers, runtime proof is a draft readback: create a draft, fetch its raw MIME, and
assert the named `From` header.

## Data Flow

1. Worker chooses an intended sender address from config or persona metadata.
2. Worker resolves display name from local config, persona registry, or Gmail send-as settings.
3. Worker builds a `MailIdentity`.
4. Worker calls `format_from_header(...)` before setting `msg["From"]`.
5. Worker sends or drafts through its existing provider-specific client.
6. Tests and optional smoke checks assert the raw/received header is named.

## Error Handling

Display-name lookup must degrade safely:

- Settings lookup 403/404/network failure: log/audit the failed resolution if the worker has an
  audit channel, then fall back to the address.
- Malformed address: fail before sending or drafting.
- Empty display name on a persona alias: allowed only when a worker test explicitly expects a bare
  `From`.

No platform helper should broaden Gmail scopes. If a worker lacks permission to read send-as
settings, it can still pass a configured display name or persona registry value.

## Out Of Scope

- Adding Gmail OAuth or Google client dependencies to `clonway-cockpit` core.
- Changing any worker from draft-only to send-capable.
- Adding approval links, email delivery of cockpit approval requests, or any new transport.
- Rewriting old delivered messages or existing drafts.
- Forcing every email to use Milo Garth. The contract is named identity, not one global sender.

## Acceptance Criteria

- `clonway_cockpit.mail_identity` formats bare and named identities correctly using only stdlib.
- Worker-template safety tests make direct ungoverned email construction visible in new workers.
- At least one live sender migration PR proves the pattern end to end before broader rollout.
- Existing no-send and compose-only invariants in xletter, xcqc, xhr, and xadmissions remain intact.
- Docs clearly state that cockpit owns sender identity policy, while workers own Gmail/client I/O.

## Test Plan For Implementation

- Unit tests for `MailIdentity` validation and `format_from_header`.
- Unit tests for resolver success, empty result, exception fallback, and preformatted header input.
- Worker-template generated-project test proving direct `messages().send`, `drafts().create`, or
  MIME `From` construction is rejected unless routed through the approved adapter.
- Repo migration tests in xops/xbook/xsource/xletter/xcqc/xadmissions as each worker adopts it.
- One runtime Gmail smoke for each live sender before marking that worker migrated.
