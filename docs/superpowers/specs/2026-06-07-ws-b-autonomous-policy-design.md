# WS-B — Autonomous-operation authorization policy (design)

**Status:** approved-to-build (operator: "go to B, keep going"), 2026-06-07
**Workstream:** WS-B (see `.claude/state/agentic-operating-workstreams.md`).
**Goal:** move the human from *approver* → *auditor*: the agent runs the reversible bookkeeping
writes autonomously, grounded in domain state — built on WS-A's `approval` seam.

## Safety frame (non-negotiable)
- **Opt-in, default OFF.** Building this ships the mechanism; it does NOT enable autonomous
  writes. The operator turns it on per-capability via an allowlist flag (informed by the
  inventory below). Default = today's behaviour (dry-run / human).
- **Money-direction excluded BY CONSTRUCTION.** A capability that moves money / changes a
  payment destination is marked `money_movement=True` and can NEVER be auto-approved, even if
  mistakenly added to an allowlist (the policy refuses it). Reversible records only.
- **Full audit trail** of every auto-applied gate (the thing that makes "just reverse it" cheap).

## Capability inventory (read-only, 2026-06-07) — the allowlist candidates
All 10 xbook write-gate walks write **reversible bookkeeping records**; NONE initiate a real
payment/transfer or change a payment destination (consistent with the repo invariant "never
fabricate bank transactions / NO Payment"):

| capability / walk | writes | class |
|---|---|---|
| schedule-bills | PlannedPaymentDate on bills | reversible record |
| approve_schedule | DRAFT→AUTHORISED bills + pay date | reversible record |
| apply_remittance | Payment matched to a landed remittance (reconciliation) | reversible record |
| reconcile_settle | Payment vs an authorised bill a *landed* debit matches (match-first) | reversible record |
| raise_invoices | create council AR invoices | reversible record |
| payroll_clear | wage journal (squares a pay run already paid) | reversible record |
| pnl_review | ManualJournal corrections (recode/amortise/loan-split) | reversible record |
| loans | config/loans.yaml + ManualJournal catch-up | reversible record |
| occupancy_sync | config/rooms.yaml | config (no money) |
| occupancy_create_contacts | new Xero contacts | reversible record |

→ none are `money_movement`; the structural exclusion guards future capabilities + the
chat-surfaced bank-detail case (a WS-C/WS-D concern, not a cockpit capability).

## Components

### Framework (clonway-cockpit) — PR 1
- **Classification:** `CapabilitySpec.money_movement: bool = False`. A capability that moves
  money sets it True → structurally un-auto-approvable.
- **Threaded gate context:** `WizardContext.capability_key` + `capability_money_movement`;
  `shell._open_capability` sets them from the running spec; `walk.confirm_apply` includes them
  (with `token` + `equivalent_cli`) in the proposal it hands the authorizer.
- **`approval.AllowlistPolicy(allowlist: set[str], *, label="")`:** `(proposal) -> bool` —
  approve iff `proposal["capability_key"] in allowlist AND not proposal["money_movement"]`.
  The money_movement check is defense-in-depth (refuses even a mis-allowlisted money capability).
- **Authorizer injection:** `serve_stdio` / `serve_agent_stdio` accept an optional
  `authorize_apply` policy used as the gate authorizer *instead of* the human token-handshake;
  `on_apply` still fires on every authorized apply (uniform audit). When neither a policy nor
  `allow_apply` is given → no authorizer (pure dry-run, unchanged default).

### xbook — PR 2
- All 10 capabilities keep `money_movement=False` (default; they're reversible records). The
  policy admits only the operator-enabled subset.
- **Opt-in flag (default OFF):** `XBOOK_AUTONOMOUS` = comma-separated capability keys to
  auto-approve (empty/unset → off → deny/dry-run, today's behaviour). When set,
  `serve_agent(--agent-stdio)` builds `AllowlistPolicy({those keys})` as the authorizer.
- **Audit:** extend `xbook/agent/audit.py` (and the existing `on_apply`=`_log_applied_gate`)
  to record every auto-applied gate — feeds WS-C's "what Milo did" digest card.

## Testing
- Framework: `AllowlistPolicy` admits an allowlisted reversible capability, refuses one not in
  the allowlist, and **refuses a money_movement capability even when allowlisted**; the gate
  proposal carries `capability_key`+`money_movement`; serve_stdio uses an injected policy and
  fires `on_apply` once on approve.
- xbook: `XBOOK_AUTONOMOUS` unset → deny (0 posts); set to `schedule-bills` → that walk
  auto-applies once + audited; a (hypothetical) money_movement capability stays denied.

## Out of scope (later workstreams)
The digest surface (WS-C) + the conversational operator (WS-D). WS-B ships the mechanism; the
operator enables it.
