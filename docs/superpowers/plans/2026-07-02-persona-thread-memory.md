# [Plan] Per-persona thread memory — bounded context, summary, forget (persona go-live Slice C)

- **Date:** 2026-07-02 · **Branch:** `claude/plan-persona-thread-memory` · **Status:** plan ready — doc-only, plan-signalled, builder implements on this branch
- **Depends on: clonway-cockpit#109** (Slice B, the add-on transport edge — must be merged into `origin/main` before Tasks 6–7 build; Tasks 1–5 build against merged #77/#79 only). PR title carries `[Wave 1]` (HR11).
- **Binding companions:** [`docs/thread-memory.md`](../../thread-memory.md) (the shipped v1 this extends), [`docs/private-memory.md`](../../private-memory.md) (#77 store), [`docs/superpowers/specs/2026-06-10-thread-memory-wiring-design.md`](../specs/2026-06-10-thread-memory-wiring-design.md) (v1 design; its "Out (later)" list is this PR's scope), `docs/superpowers/plans/2026-07-02-chat-addon-transport.md` (#109 — the transport seam, env contract, `fake_dm_envelope`, `run_fake`), [`docs/persona-platform-go-live-plan.md`](../../persona-platform-go-live-plan.md) (Slice C)

> **For agentic workers:** REQUIRED SUB-SKILL: implement this plan task-by-task (Claude: superpowers:subagent-driven-development or superpowers:executing-plans; Codex: the same phase/TDD/verification discipline). Steps use checkbox (`- [ ]`) syntax for tracking. Tick checkboxes as work lands and commit this plan with the code.

## Why (problem & goal)

#79 shipped v1 thread memory (`chat_memory.py`: `scope_for_space` + `ThreadTranscript` +
`remembering_responder`) and its spec explicitly deferred the rest: *"a memory
reflector/summariser … a retention sweep is its own slice"*, coordinated/atomic appends *"land with
the live-deploy slice"*. #109 (Slice B) ships the deployable edge but wires the **stateless**
`gateway_responder` and names *"Live-deploy memory wiring: `remembering_responder` + mandatory
dedup store (Slice C config)"* as a follow-up. So today a live persona would either be amnesiac,
or remember with unbounded on-disk growth, O(turns) appends forever, non-atomic writes on a
GCSFuse mount, and no way to delete a conversation.

**Goal:** a persona's turn context becomes **thread history window + compacted per-(persona,
thread) summary**, with pinned retention/size bounds, atomic writes, corrupt-store degrade, a
tested `forget` operation, and the memory wiring at exactly the seam #109 defines
(`build_serve_app` env selection + the `--fake` REPL) — so multi-turn memory is provable locally
with zero Google/Workspace registration.

## Current-state evidence (read before coding)

- `src/clonway_cockpit/chat_memory.py` (merged #79): `scope_for_space` (collision-proof slug),
  `ThreadTranscript.record/forget/recent` (`turn-NNNNNN` Fact files; `_turn_index` is the single
  definition of "what is a turn" for ordering AND the next-index counter), `remembering_responder`
  (splices `recent(history_turns)` between soul and message; rolls back an orphan user turn;
  empty `message.space` → stateless; `GatewayError`/empty reply record nothing). v1 limits it
  documents: single writer per (persona, space); O(turns) append; every turn kept forever.
- `src/clonway_cockpit/private_memory.py` (merged #77): `PersonaMemory.thread(scope)` →
  `PrivateScope` at `<base>/<handle>/threads/<scope>`; `remember` currently uses plain
  `path.write_text` (NOT atomic); reads are best-effort (`SharedMemory` loader skips unreadable
  files, never raises). Persona isolation is structural (per-`handle` subtree).
- `src/clonway_cockpit/obs/atomicio.py`: `atomic_write_bytes` (tmp-sibling `os.replace`) + a
  process-wide `_WRITE_LOCK` — the platform's atomic-write pattern for GCSFuse-mounted state
  (born from the 2026-06-11 xbook append-storm stall).
- `src/clonway_cockpit/signals/subscribe.py`: `FileCursorStore` (atomic tmp→rename JSON) /
  `GcsCursorStore` (generation preconditions; documented **single-writer, min-instances=1**
  discipline) — the house storage-pattern precedent this slice follows rather than inventing a
  new store.
- `tests/test_chat_memory.py`: `RecordingCompleter`, `FailingCompleter`, `_registry`, `_event` /
  `_owner_dm` (the **nested add-on envelope** shape mirroring `tests/test_chat_transport.py::addon_message`)
  — reuse these helpers; do not invent new envelope shapes (HR12).
- #109's plan (`gh pr diff 109 --repo hearth-care/clonway-cockpit`, binding artifact
  `docs/superpowers/plans/2026-07-02-chat-addon-transport.md`): `build_serve_app(environ)` env
  contract (`CLONWAY_CHAT_*`), `build_addon_app`, `fake_dm_envelope(text, *, email, space_id,
  space_type, msg_id)`, `run_fake(lines, …)`, `FileSeenStore` durable dedup, executors
  `run_inline`/`spawn_daemon_thread`.
- Salvaged from stale branch `Codex/quarter-plan-per-persona-memory` (2026-06-10 doc-only
  workstream brief, `docs/workstreams/2026-06-10-per-persona-memory.md`): **kept** — its
  acceptance criteria "a persona can remember context within its own thread/space" (extended here
  to *bounded* context + summary), "private memory does not leak across personas" (invariant rows
  1–2), "shared memory writes require owner confirmation" + "tests for quoted content not
  becoming shared memory" (invariant row 10: a full conversation *including compaction* leaves a
  `SharedMemory` reader empty), and its work item "define retention and storage paths" (the
  bounds table + binding storage decision below). **Dropped** — "ship and watch the Chat
  transport first" as an unstructured gate (superseded by `[Wave 1]` + the explicit
  `Depends on: clonway-cockpit#109` line, HR11), "design thread/space scoped memory" (shipped as
  #77/#79 — this PR extends, it does not redesign), and its "open one or more implementation PRs
  as needed" framing (one unit of work = one PR; the builder implements on this branch).

## Binding decisions (do not re-litigate)

1. **Storage stays the merged #77 Fact store — file-backed on a durable mount. One source of
   truth (HR6).** No parallel GCS-API thread store in this PR: the platform's Cloud Run pattern
   for this data is a mounted volume/GCSFuse path (`docs/thread-memory.md` "directory
   discipline") with atomic tmp→rename writes (`obs/atomicio.py`), exactly the choice #109 made
   for `FileSeenStore` and `FileCursorStore` made for cursors. A GCS-API-backed store is a named
   follow-up. Cross-**process** single-writer per (persona, space) remains a deploy constraint
   (min-instances=1 — same discipline `GcsCursorStore` documents); this PR removes the
   cross-**thread** hazard inside one process (a real window once #109's `spawn_daemon_thread`
   handles two events concurrently).
2. **Summarisation in this slice is deterministic and extractive** — folding a turn contributes
   the line `f"{fact.kind}: {fact.summary}"` (the store's existing ≤120-char preview; HR6 — no
   second preview rule). No model call in the memory layer: zero spend, fully testable, works in
   `--fake` with zero Google and zero model. Model-quality summarisation is a named follow-up
   behind the same on-disk contract (the summary Fact is the contract; the folding function is
   the swappable seam).
3. **The summary Fact is the authority on what has been folded.** Name `thread-summary` (not a
   `turn-*` name, so the existing `_turn_index` logic ignores it by construction), `kind`
   `summary`, `body` = the rolling summary text, `source` = `folded-through: NNNNNN` (zero-padded
   index of the newest folded turn). Replay excludes turns with index ≤ folded-through, so the
   crash window (summary written, folded turns not yet deleted) can never double-replay; the next
   `record()` sweeps leftovers. Unparseable `folded-through` → treated as `-1` (replay everything
   on disk; worst case one benign re-fold after a torn write, never a crash).
4. **Next-index rule (prevents index reuse after folding):**
   `next = max([folded_through] + on_disk_turn_indices) + 1`. Without the `folded_through` term, a
   thread whose remaining turns were lost out-of-band would restart at index 0 ≤ folded-through
   and every new turn would be invisible to replay.
5. **Bounds are module constants (single source of truth), overridable per-instance for tests:**

   | Constant | Value | Rationale |
   |---|---|---|
   | `DEFAULT_TURNS` | 12 (existing, unchanged) | replayed window ≈ 6 exchanges — #79's pinned prompt-size bound |
   | `MAX_TURNS_ON_DISK` | 200 | compaction trigger: `record` scans the thread dir (documented O(turns) cost), 200 small files keeps that trivial; 200 turns ≈ 100 exchanges of un-compacted recall; ≲1 MB/thread worst case (Chat messages cap at ~4 KB) |
   | `KEEP_TURNS` | 100 | compaction halves the thread (amortised: one fold per ~100 turns); constraint: `2 × DEFAULT_TURNS ≤ KEEP_TURNS < MAX_TURNS_ON_DISK` so the replay window never straddles a fold boundary right after compaction |
   | `SUMMARY_MAX_CHARS` | 4000 | ≈1k tokens of bounded per-call prompt overhead; a folded line is ≤ 129 chars (`"persona: "` = 9 + preview ≤ 120), so ≥ 30 newest folded lines always survive truncation (4000 / 130 = 30.7) |

6. **`remembering_responder` keeps its exact signature** — it swaps `recent(history_turns)` for
   `context(history_turns)` internally, so #109's responder seam takes it unchanged and every
   existing caller/test keeps passing. The summary is spliced as a second `system` message
   directly after the soul: `SUMMARY_HEADER = "Earlier in this conversation (compacted summary):"`
   + `"\n"` + body.
7. **Memory wiring is opt-in by env.** `CLONWAY_CHAT_MEMORY_DIR` set → `build_serve_app` uses the
   memory responder; unset → stateless `gateway_responder`, byte-for-byte the behaviour #109
   ships. The selection lives in one named function (`chat_addon.build_responder`) so it is
   testable without a server or a model.
8. **Content-free logging.** The memory layer never logs message text, sender emails, space ids,
   or **scope values** (a scope embeds a readable prefix of the space id). Warnings carry counts
   only. Same discipline as the gateway and #109's edge; a test asserts it.
9. **Not touched:** `GovernedWriter`/shared-tier promotion, the owner-only-command air-gap,
   `ChatRouter`/`GroupChatOrchestrator`, the `confirm_apply` write gate, gateway semantics.

## Non-goals (out of scope for this PR)

- Model-based summarisation quality (follow-up behind the summary-Fact contract, decision 2).
- A GCS-API-backed thread store (follow-up; decision 1 binds file-backed here).
- Cross-space/cross-surface recall or auto-promotion to shared memory (still `GovernedWriter`,
  owner-gated); semantic/embedding recall (keyword `recall` already exists).
- Group-chat Slice D features; the Cloud Run deploy/IAM/manifest (OPERATOR TODO in #109);
  Milo/xbook wiring (cross-repo follow-up); encryption-at-rest (consumer directory discipline);
  a cross-process file lock (deploy constraint per decision 1).

## Functional contract

New/changed public API (all covered by tests; everything else in the two modules is unchanged):

| Name | Contract |
|---|---|
| `chat_memory.MAX_TURNS_ON_DISK = 200`, `KEEP_TURNS = 100`, `SUMMARY_MAX_CHARS = 4000` | module constants per decision 5 (single source of truth) |
| `chat_memory.SUMMARY_FACT = "thread-summary"`, `SUMMARY_HEADER` | reserved fact name + the exact replay header (decision 3/6) |
| `ThreadTranscript(base, handle, scope, *, max_turns=MAX_TURNS_ON_DISK, keep_turns=KEEP_TURNS, summary_max_chars=SUMMARY_MAX_CHARS)` | keyword overrides exist for tests; production callers use defaults |
| `ThreadTranscript.record(role, text) -> str \| None` | as today, plus: after writing, sweeps turns with index ≤ folded-through, and when unfolded-turn count > `max_turns`, folds the oldest `count − keep_turns` turns into the summary Fact and deletes them (write summary first, delete after — decision 3) |
| `ThreadTranscript.summary() -> str \| None` | the rolling summary body, `None` when absent/unreadable |
| `ThreadTranscript.context(limit=DEFAULT_TURNS) -> list[Message]` | `[{"role": "system", "content": SUMMARY_HEADER + "\n" + body}]` when a summary exists, then `recent(limit)`; `limit` bounds turns only |
| `ThreadTranscript.recent(limit)` | as today, but excludes turns with index ≤ folded-through |
| `ThreadTranscript.forget_thread() -> bool` | deletes the whole (persona, thread) scope directory — turns, summary, and any corrupt strays; `True` iff it existed; delegates to `PersonaMemory.forget_thread` (path shape stays owned by `private_memory`, HR6) |
| `PersonaMemory.forget_thread(scope) -> bool` | validates `scope`, removes `<base>/<handle>/threads/<scope>` recursively; `False` if absent |
| `PrivateScope.path -> Path` | the scope directory (read-only accessor so callers/tests never hand-build the layout) |
| `PrivateScope.remember(...)` | same signature/behaviour, now written via `obs.atomicio.atomic_write_bytes` (tmp-sibling `os.replace`) |
| `python -m clonway_cockpit.chat_memory forget --memory-base DIR --handle H --space SPACE_ID` | operator deletion: derives the scope via `scope_for_space`, calls `forget_thread`; prints exactly `forgotten` or `nothing to forget`, exit 0; invalid handle → exit 2, content-free error |
| `chat_addon.build_responder(colleagues, completer, *, role, memory_dir: Path \| None)` *(Task 6, post-#109)* | `memory_dir` set → `remembering_responder(..., memory_base=memory_dir)`; `None` → `gateway_responder(...)` — the one seam `build_serve_app` calls |
| env `CLONWAY_CHAT_MEMORY_DIR` *(Task 6, post-#109)* | when set, `build_serve_app` passes it as `memory_dir`; unset → stateless (exactly as #109 ships) |
| `run_fake(..., memory_dir: Path \| None = None)` + `--memory-dir` *(Task 7, post-#109)* | fake REPL with per-thread memory over a deterministic `EchoCompleter` (below) — multi-turn provable with zero Google/model |

`EchoCompleter` (Task 7, in `chat_addon`): `complete(messages, *, role)` returns
`f"[{len(messages)} msgs] {messages[-1]['content']}"` — deterministic, so history growth is
directly observable in the reply text.

## Safety invariants (cell table — every row bound to a named test; HR3)

| # | State | Required behaviour | Test (in `tests/test_chat_memory.py` unless noted) |
|---|---|---|---|
| 1 | two personas engaged in the same space | each transcript holds only its own engaged turns; A's context never contains B's turns (structural: per-`handle` subtree) | existing `test_responder_isolates_transcripts_per_persona` (regression, stays green) |
| 2 | two personas, compaction has run for both | A's context never contains B's **summary** | `test_summary_isolation_per_persona` |
| 3 | one persona, a DM space and a ROOM space | ROOM turns/summary never appear in DM context and vice versa (both directions asserted) | `test_dm_and_room_contexts_never_cross` |
| 4 | any turn/summary write interrupted (simulated `os.replace` failure) | prior file content intact, no `.tmp` litter — never a torn fact | `test_remember_is_atomic_under_replace_failure` (in `tests/test_private_memory.py`) |
| 5 | two same-process threads `record()` concurrently on one thread | both turns land with distinct indices; none lost (module record lock) | `test_concurrent_records_in_one_process_lose_nothing` |
| 6 | a corrupt/unparseable turn file in the thread | skipped; remaining turns replayed; exactly one warning, content-free (no text/email/space id/scope) | `test_corrupt_turn_file_degrades_and_warns_content_free` |
| 7 | corrupt/garbage `thread-summary` file | treated as absent: no summary message, replay proceeds, no crash | `test_corrupt_summary_degrades_to_no_summary` |
| 8 | store root missing entirely | `context()`/`recent()`/`summary()` return empty/`None`, never raise; first `record()` creates the directories | `test_missing_store_reads_empty_then_record_creates` |
| 9 | `forget_thread` on a populated thread (turns + summary + a corrupt stray) | directory gone; next `context()` is `[]`; second call returns `False` (clean no-op) | `test_forget_thread_removes_turns_and_summary` |
| 10 | a full conversation incl. window overflow + compaction | a `SharedMemory` reader over the same base stays empty — session memory never becomes shared truth | `test_conversation_and_compaction_never_write_shared_memory` (extends #79's `test_responder_never_writes_to_shared_memory`) |
| 11 | crash window: summary written, folded turns not yet deleted | folded turns excluded from replay (no double context); swept on the next `record()` | `test_crash_window_folded_turns_are_not_double_replayed` |
| 12 | only the summary remains (turns lost out-of-band) | next index > folded-through — a new turn never reuses a folded index and always replays | `test_next_index_never_reuses_folded_indices` |
| 13 | non-operator DM through the edge with memory wired (post-#109) | `200` `{}`, zero posts, **zero turn files** — the air-gap sits upstream of memory | `test_edge_non_operator_dm_records_nothing_with_memory_on` (in `tests/test_chat_addon.py`) |
| 14 | `GatewayError` / empty reply / blank text | nothing recorded (the #79 contract, preserved through the `context()` change) | existing `test_responder_model_error_records_no_turn`, `test_responder_empty_reply_records_no_turn`, `test_transcript_does_not_record_blank_text` (regressions, stay green) |

No money is written anywhere in this PR. The durable-state writes are turn/summary Fact files and
directory deletion; their idempotency/partial-failure story is decisions 3–4 (folded-through is
the authority; sweep-on-next-record is the recovery; `forget_thread` is idempotent by returning
`False` on the second call) (HR4).

## Full state set (HR5 — each an acceptance checkbox with its named test)

- [ ] new thread (no scope dir): context `[]`, first exchange recorded — existing
  `test_responder_first_call_has_no_history_then_injects_prior_turns` (regression)
- [ ] continuing thread under the window: prior turns replayed chronologically — existing
  `test_end_to_end_router_dm_remembers_across_turns` (regression)
- [ ] window overflow → compaction + summary (worked example below) —
  `test_overflow_compacts_oldest_turns_into_summary`
- [ ] repeated overflow → summary truncates whole oldest lines to fit `summary_max_chars` —
  `test_summary_truncates_oldest_lines_at_line_boundary`; single overlong line hard-truncates to
  `line[:summary_max_chars]` — `test_summary_single_overlong_line_hard_truncates`
- [ ] corrupt turn file → degrade + one content-free warning — invariant row 6
- [ ] corrupt summary → degrade to no summary — invariant row 7
- [ ] missing store → empty reads, `record` creates — invariant row 8
- [ ] crash-window / folded-index reuse — invariant rows 11–12
- [ ] cross-persona isolation (turns + summaries) — invariant rows 1–2
- [ ] DM ↔ ROOM isolation, both directions — invariant row 3
- [ ] empty `message.space` → stateless (no bogus bucket) — existing
  `test_responder_empty_space_is_stateless` (regression)
- [ ] redelivered message with dedup hooks wired → one turn pair — existing
  `test_end_to_end_redelivery_with_dedup_hooks_records_once` (regression)
- [ ] deletion honoured: library `forget_thread` + operator CLI — invariant row 9,
  `test_forget_cli_deletes_the_thread`, `test_forget_cli_nothing_to_forget`
- [ ] summary reaches the model after the soul — `test_responder_splices_summary_after_soul`
- [ ] *(post-#109)* owner DM through the real edge remembers across POSTs (real envelopes) —
  `test_edge_dm_remembers_across_posts_with_memory_wired`
- [ ] *(post-#109)* non-operator DM through the edge records nothing — invariant row 13
- [ ] *(post-#109)* `build_responder` selects memory vs stateless by `memory_dir` —
  `test_build_responder_memory_dir_selects_memory`; `build_serve_app` plumbs the env var —
  `test_build_serve_app_passes_memory_dir_env`
- [ ] *(post-#109)* `--fake` REPL multi-turn with `--memory-dir` —
  `test_run_fake_with_memory_dir_carries_history`

## Real-contract grounding (HR12)

- All event-driven tests use the **nested Workspace add-on envelope**
  (`chat.messagePayload.{message,space,user}` — the shape `normalize_event` flattens), via the
  existing fixtures: `tests/test_chat_memory.py::_event`/`_owner_dm` (which mirror the core's
  `tests/test_chat_transport.py::addon_message`) and, for edge tests, #109's `fake_dm_envelope`
  (whose own boundary test pins `normalize_event(fake_dm_envelope("x")).kind == MESSAGE`).
- Space typing follows the core contract: `space.type` upper-cased, `"DM"` routes the DM path,
  anything else (e.g. `"ROOM"`) the space path (`chat_transport.py::_flatten`/`handle_event`).
- QA acceptance line: **fixtures use only the envelope shapes the merged core already normalises
  — no invented event kinds, no flat shapes pretending to be add-on events; the DM/ROOM strings
  match `NormalizedChatEvent.space_type`'s documented values.**

## Worked examples (HR7 — computed from the shipped test fixtures)

**Compaction** (test bounds `max_turns=4, keep_turns=2`): record `t0..t4` alternating
`USER/PERSONA/USER/PERSONA/USER` → after the 5th record, count 5 > 4 → fold oldest
`5 − 2 = 3` turns (`turn-000000..000002`), `folded-through: 000002`. On disk: `turn-000003`,
`turn-000004`, `thread-summary`. `summary()` = `"user: t0\npersona: t1\nuser: t2"`.
`context(12)` = 3 messages: `system` (`SUMMARY_HEADER` + the 3 lines), `assistant` (`t3`),
`user` (`t4`).

**Summary truncation** (`summary_max_chars=20`): candidate body
`"user: t0\npersona: t1\nuser: t2"` is 8+1+11+1+8 = **29 chars** > 20 → drop the oldest whole
line → `"persona: t1\nuser: t2"` = 11+1+8 = **20 chars** ✓ (newest lines survive).

**Production bounds:** worst-case folded line = 9 (`"persona: "`) + 120 (preview cap) = 129
chars; 4000 // 130 = **30** — at least the 30 newest folded lines always fit (decision 5).

**Fake REPL echo** (Task 7): input lines `["hi", "again"]` with `--memory-dir` set → replies
exactly `"[2 msgs] hi"` (system + user), then `"[4 msgs] again"` (system + user `hi` +
assistant `[2 msgs] hi` + user `again`) — history growth visible in the reply text.

---

## Implementation plan

**Goal:** bounded per-(persona, thread) memory — window + summary — durable, atomic, deletable,
wired at #109's seam, provable locally with `--fake`.

**Architecture:** all retention/summary/deletion logic lives in `chat_memory.py` on top of the
unchanged #77 store (`private_memory.py` gains only atomic writes, `forget_thread`, and the
`path` accessor). The edge (`chat_addon.py`, post-#109) selects the responder in one named
function. Pure logic (folding, truncation, index rules) is separated from I/O (Fact writes via
`atomicio`); no module gains a network dependency.

**Tech stack:** Python stdlib only (`hashlib`, `logging`, `shutil`, `threading`, `argparse`).
**No new dependencies.**

### Global constraints

- Safety invariants: the 14-row cell table above — one test per row, on the code path named in
  the row (HR3).
- Sources of truth (HR6): bounds = the three `chat_memory` constants; turn identity/ordering =
  `_turn_index` (unchanged, still the only definition); folded state = the `thread-summary`
  Fact's `folded-through` source field; on-disk layout = `private_memory` (`PersonaMemory.thread`
  / `forget_thread` / `PrivateScope.path` — `chat_memory` never hand-builds the path); summary
  splice header = `SUMMARY_HEADER`; env name `CLONWAY_CHAT_MEMORY_DIR` defined once in
  `chat_addon`.
- Repo rules: no second write path (this PR posts nothing and never touches `confirm_apply`);
  model calls only via the gateway (none added — decision 2); content-free logging (decision 8);
  `CHANGELOG.md` gets an `## [Unreleased]` entry (`src/` change with worker-visible surface, per
  `docs/release-policy.md`).
- Operator-facing: **yes** — a new deploy env knob (`CLONWAY_CHAT_MEMORY_DIR`), a new local-dev
  flag (`--memory-dir`), and a new operator deletion command (the `forget` CLI) ⇒ post a
  `RUNBOOK DELTA` comment on `hearth-care/auto-orchestrator#196` and repeat it in the DONE
  comment (HR1) — checkbox in Task 8. Retention numbers are code defaults; no operator authoring
  needed for them.
- **Depends on: clonway-cockpit#109** (must be merged into `origin/main` before Tasks 6–7 build —
  if it is not merged when this plan is claimed, flip `agent:blocked` per the builder
  PREREQUISITES rule rather than improvising against the unmerged seam). Tasks 1–5 and 8 build
  against merged #77/#79 only. PR title carries `[Wave 1]` (HR11). If the merged `chat_addon`
  drifts from #109's plan in a signature detail, adapt at the call site and record the deviation
  in HANDOFF NOTES — never fork a second seam.
- Gates (exact canonical commands QA re-runs, verbatim, full scope — paste output tails in the
  DONE comment; HR2): `make lint`, `make format`, `make typecheck`, `make test` (one-shot:
  `make check`).

### Task 1 — bounded transcript core: folded-through model, `context()`, compaction

**Files:** modify `src/clonway_cockpit/chat_memory.py`, `src/clonway_cockpit/private_memory.py`
(only `PrivateScope.path`); extend `tests/test_chat_memory.py`.
**Production call site (HR9):** `remembering_responder`'s `transcript.record(...)` /
`transcript.context(...)` — the responder `ChatRouter` deployments already consume; Task 5
asserts the responder path, Task 6 completes the edge wiring.
**Interfaces:** the constants, `SUMMARY_FACT`, `SUMMARY_HEADER`, `ThreadTranscript` keyword
bounds, `summary()`, `context()`, the `recent()` folded-through exclusion, the next-index rule.

- [x] **Step 1 — failing tests** (assert replayed messages and on-disk file sets — observable
  behaviour, not internals; HR8). Embed verbatim:

```python
def test_overflow_compacts_oldest_turns_into_summary(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x", max_turns=4, keep_turns=2)
    for i, text in enumerate(["t0", "t1", "t2", "t3", "t4"]):
        t.record(USER if i % 2 == 0 else PERSONA, text)
    assert t.summary() == "user: t0\npersona: t1\nuser: t2"
    ctx = t.context(12)
    assert [m["role"] for m in ctx] == ["system", "assistant", "user"]
    assert ctx[0]["content"] == (
        "Earlier in this conversation (compacted summary):\nuser: t0\npersona: t1\nuser: t2"
    )
    assert [m["content"] for m in ctx[1:]] == ["t3", "t4"]
    names = {p.name for p in (tmp_path / "milo" / "threads" / "dm-x").glob("*.md")}
    assert names == {"turn-000003.md", "turn-000004.md", "thread-summary.md"}


def test_summary_truncates_oldest_lines_at_line_boundary(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x", max_turns=4, keep_turns=2, summary_max_chars=20)
    for i, text in enumerate(["t0", "t1", "t2", "t3", "t4"]):
        t.record(USER if i % 2 == 0 else PERSONA, text)
    assert t.summary() == "persona: t1\nuser: t2"  # 29 chars > 20 → oldest whole line dropped


def test_crash_window_folded_turns_are_not_double_replayed(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x", max_turns=4, keep_turns=2)
    for i, text in enumerate(["t0", "t1", "t2", "t3", "t4"]):
        t.record(USER if i % 2 == 0 else PERSONA, text)
    # simulate the crash window: a folded turn re-appears (summary written, delete never ran)
    PersonaMemory(tmp_path, "milo").thread("dm-x").remember(
        name="turn-000001", kind=PERSONA, summary="t1", body="t1"
    )
    assert [m["content"] for m in t.context(12)[1:]] == ["t3", "t4"]  # ≤ folded-through: excluded
    t.record(USER, "t5")  # the next record sweeps the leftover
    names = {p.name for p in (tmp_path / "milo" / "threads" / "dm-x").glob("turn-*.md")}
    assert "turn-000001.md" not in names


def test_next_index_never_reuses_folded_indices(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x", max_turns=4, keep_turns=2)
    for i, text in enumerate(["t0", "t1", "t2", "t3", "t4"]):
        t.record(USER if i % 2 == 0 else PERSONA, text)
    for p in (tmp_path / "milo" / "threads" / "dm-x").glob("turn-*.md"):
        p.unlink()  # turns lost out-of-band; only thread-summary remains
    name = t.record(USER, "fresh")
    # rule: next = max([folded_through] + on_disk_indices) + 1 = max([2]) + 1 = 3.
    # Reusing a lost-out-of-band NAME is fine; the guarantee is the index can never
    # fall at or below folded-through (which would make the new turn invisible to replay).
    assert name == "turn-000003"
    assert [m["content"] for m in t.context(12)[1:]] == ["fresh"]  # replayed, not swallowed
```
- [x] **Step 2 — run, confirm RED:** `uv run pytest tests/test_chat_memory.py -q` → expect
  `TypeError: ... unexpected keyword argument 'max_turns'` first (proves load-bearing).
- [x] **Step 3 — implement:** constructor bounds (validate `2 <= keep_turns < max_turns` and
  `summary_max_chars >= 1`, `ValueError` otherwise); `_folded_through()` (parse the summary
  Fact's `source` with `re.search(r"folded-through:\s*(\d+)")`, unparseable/absent → `-1`);
  `recent()`/`_next_index` honour decision 3/4; `record()` → write turn, sweep
  `idx <= folded_through`, then if unfolded count > `max_turns` fold the oldest
  `count − keep_turns`: build lines `f"{fact.kind}: {fact.summary}"`, append to the existing
  body, drop whole head lines while over `summary_max_chars` (a single overlong line →
  `line[:summary_max_chars]`), `remember(name=SUMMARY_FACT, kind="summary", summary=<first
  line>, body=..., source=f"folded-through: {idx:06d}")`, then `forget` each folded turn;
  `summary()` / `context()` per the contract table. Add `PrivateScope.path` property.
- [x] **Step 4 — verify:** `uv run pytest tests/test_chat_memory.py -q` → all pass (including
  every pre-existing #79 test, untouched).
- [x] **Step 5 — commit:** `feat(chat-memory): bounded transcript — folded-through summary, context(), compaction`

### Task 2 — atomic writes + same-process concurrency

**Files:** modify `src/clonway_cockpit/private_memory.py`, `src/clonway_cockpit/chat_memory.py`;
extend `tests/test_private_memory.py`, `tests/test_chat_memory.py`.
**Production call site (HR9):** every `PrivateScope.remember` (turns, summaries, working notes)
and `ThreadTranscript.record` under #109's `spawn_daemon_thread` concurrency.

- [x] **Step 1 — failing tests.** Embed verbatim (imports: `threading`, `pytest`,
  `PersonaMemory`):

```python
def test_remember_is_atomic_under_replace_failure(tmp_path, monkeypatch):
    scope = PersonaMemory(tmp_path, "milo").thread("dm-x")
    scope.remember(name="note", kind="note", summary="v1", body="v1")

    def boom(src, dst):
        raise OSError("simulated crash mid-write")

    monkeypatch.setattr("clonway_cockpit.obs.atomicio.os.replace", boom)
    with pytest.raises(OSError):
        scope.remember(name="note", kind="note", summary="v2", body="v2")
    monkeypatch.undo()
    fresh = PersonaMemory(tmp_path, "milo").thread("dm-x")
    fact = fresh.get("note")
    assert fact is not None and fact.body == "v1"  # never a torn/half file
    assert not list((tmp_path / "milo" / "threads" / "dm-x").glob("*.tmp"))


def test_concurrent_records_in_one_process_lose_nothing(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x")
    start = threading.Barrier(2)

    def worker(text: str) -> None:
        start.wait()
        t.record(USER, text)

    threads = [threading.Thread(target=worker, args=(f"m{i}",)) for i in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(m["content"] for m in t.recent(12)) == ["m0", "m1"]
```

- [x] **Step 2 — RED** (`uv run pytest tests/test_private_memory.py tests/test_chat_memory.py -q`
  — the atomic test fails because `remember` uses `write_text`; the concurrency test flakes/fails
  on a lost index).
- [x] **Step 3 — implement:** `PrivateScope.remember` writes via
  `atomic_write_bytes(path, rendered.encode("utf-8"))` (import from `clonway_cockpit.obs.atomicio`
  — reuse, do not copy); add a module-level `_RECORD_LOCK = threading.Lock()` in `chat_memory`
  held across `record()`'s whole read-index → write → sweep → compact sequence (mirrors
  `atomicio._WRITE_LOCK`; serialises all transcripts in-process, which is correct and cheap).
- [x] **Step 4 — verify:** same command → all pass. **Step 5 — commit:**
  `feat(memory): atomic Fact writes + per-process record lock`

### Task 3 — corrupt/missing-store degrade with a content-free warning

**Files:** modify `src/clonway_cockpit/chat_memory.py`; extend `tests/test_chat_memory.py`.
**Production call site (HR9):** `context()`/`recent()` inside `remembering_responder` — the path
a live redelivered/torn file would hit.

- [x] **Step 1 — failing tests.** Embed verbatim (imports: `logging`):

```python
def test_corrupt_turn_file_degrades_and_warns_content_free(tmp_path, caplog):
    t = ThreadTranscript(tmp_path, "milo", "dm-x")
    t.record(USER, "the secret figures")
    t.record(PERSONA, "noted")
    (tmp_path / "milo" / "threads" / "dm-x" / "turn-000000.md").write_text("\x00garbage")
    with caplog.at_level(logging.WARNING, logger="clonway_cockpit.chat_memory"):
        ctx = t.context(12)
    assert [m["content"] for m in ctx] == ["noted"]  # degraded to the readable remainder
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "1 unreadable turn file" in joined
    assert "secret" not in joined and "dm-x" not in joined  # content-free (no text, no scope)


def test_corrupt_summary_degrades_to_no_summary(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x", max_turns=4, keep_turns=2)
    for i, text in enumerate(["t0", "t1", "t2", "t3", "t4"]):
        t.record(USER if i % 2 == 0 else PERSONA, text)
    (tmp_path / "milo" / "threads" / "dm-x" / "thread-summary.md").write_text("\x00garbage")
    assert t.summary() is None
    assert [m["role"] for m in t.context(12)] == ["assistant", "user"]  # no system note, no crash


def test_missing_store_reads_empty_then_record_creates(tmp_path):
    t = ThreadTranscript(tmp_path / "nowhere", "milo", "dm-x")
    assert t.context(12) == [] and t.summary() is None
    assert t.record(USER, "hello") == "turn-000000"
```

- [x] **Step 2 — RED** (the warning does not exist yet; the corrupt-summary case may crash on the
  unparseable source), **Step 3 — implement:** in `recent()`/`context()`, count
  `turn-*.md` files under `PrivateScope.path` vs parsed turn facts; on mismatch emit ONE
  `logging.getLogger("clonway_cockpit.chat_memory").warning("chat_memory: skipped %d unreadable turn file(s) in one thread", n)`
  — counts only, never paths/scopes/text (decision 8). Corrupt summary: `load_fact` returning
  `None`/missing `body` → `summary()` `None`, `folded-through` `-1`.
- [x] **Step 4 — verify** (`uv run pytest tests/test_chat_memory.py -q`), **Step 5 — commit:**
  `feat(chat-memory): corrupt/missing-store degrade + content-free warning`

### Task 4 — deletion honoured: `forget_thread` + the operator `forget` CLI

**Files:** modify `src/clonway_cockpit/private_memory.py`, `src/clonway_cockpit/chat_memory.py`
(argparse `main(argv=None) -> int` + `if __name__ == "__main__": raise SystemExit(main())`);
extend `tests/test_private_memory.py`, `tests/test_chat_memory.py`.
**Production call site (HR9):** the module CLI `python -m clonway_cockpit.chat_memory forget …`
— the operator's deletion surface; `ThreadTranscript.forget_thread` is its engine and the
library API.

- [ ] **Step 1 — failing tests.** Embed verbatim:

```python
def test_forget_thread_removes_turns_and_summary(tmp_path):
    t = ThreadTranscript(tmp_path, "milo", "dm-x", max_turns=4, keep_turns=2)
    for i in range(5):
        t.record(USER if i % 2 == 0 else PERSONA, f"t{i}")
    (tmp_path / "milo" / "threads" / "dm-x" / "stray.bin").write_bytes(b"\x00")  # corrupt stray
    assert t.forget_thread() is True
    assert not (tmp_path / "milo" / "threads" / "dm-x").exists()
    assert t.context(12) == []          # a forgotten thread reads as brand new
    assert t.forget_thread() is False   # idempotent no-op


def test_forget_cli_deletes_the_thread(tmp_path, capsys):
    from clonway_cockpit import chat_memory

    scope = scope_for_space("spaces/AAA")
    ThreadTranscript(tmp_path, "milo", scope).record(USER, "hello")
    rc = chat_memory.main(
        ["forget", "--memory-base", str(tmp_path), "--handle", "milo", "--space", "spaces/AAA"]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "forgotten"
    assert not (tmp_path / "milo" / "threads" / scope).exists()


def test_forget_cli_nothing_to_forget(tmp_path, capsys):
    from clonway_cockpit import chat_memory

    rc = chat_memory.main(
        ["forget", "--memory-base", str(tmp_path), "--handle", "milo", "--space", "spaces/ZZZ"]
    )
    assert rc == 0
    assert capsys.readouterr().out.strip() == "nothing to forget"
```

- [ ] **Step 2 — RED** (`AttributeError: ... no attribute 'main'` / `forget_thread`),
  **Step 3 — implement:** `PersonaMemory.forget_thread(scope)` = validate slug,
  `shutil.rmtree(dir)` if it exists (propagate real FS errors — same posture as
  `PrivateScope.forget`); `ThreadTranscript.forget_thread()` delegates;
  CLI: one `forget` subcommand, derive `scope_for_space(args.space)`, print exactly
  `forgotten`/`nothing to forget`, return 0; an invalid `--handle` → content-free message on
  stderr, return 2.
- [ ] **Step 4 — verify** (`uv run pytest tests/test_chat_memory.py tests/test_private_memory.py -q`),
  **Step 5 — commit:** `feat(chat-memory): forget_thread + operator forget CLI`

### Task 5 — responder context upgrade + isolation/shared-tier invariants

**Files:** modify `src/clonway_cockpit/chat_memory.py` (`remembering_responder`: `recent` →
`context`); extend `tests/test_chat_memory.py`.
**Production call site (HR9):** `remembering_responder` — the exact callable #109's seam
receives in Task 6.

- [ ] **Step 1 — failing tests.** Embed verbatim (reuses the file's existing `RecordingCompleter`
  / `_registry` helpers and `Persona` / `ChatMessage` / `SharedMemory` imports):

```python
def test_responder_splices_summary_after_soul(tmp_path):
    reg = _registry("milo")
    comp = RecordingCompleter("ok")
    respond = remembering_responder(reg, comp, role="chat", memory_base=tmp_path)
    pre = ThreadTranscript(tmp_path, "milo", scope_for_space("spaces/AAA"), max_turns=4, keep_turns=2)
    for i in range(5):
        pre.record(USER if i % 2 == 0 else PERSONA, f"t{i}")  # summary now on disk
    msg = ChatMessage.from_text("and now?", author="owner", is_owner=True, space="spaces/AAA")
    respond(Persona("milo", "Milo", "milo domain"), msg)
    roles = [m["role"] for m in comp.calls[0]]
    assert roles == ["system", "system", "assistant", "user", "user"]  # soul, summary, t3, t4, current
    assert comp.calls[0][1]["content"].startswith("Earlier in this conversation")


def test_summary_isolation_per_persona(tmp_path):
    for handle in ("milo", "iris"):
        pre = ThreadTranscript(tmp_path, handle, scope_for_space("spaces/AAA"), max_turns=4, keep_turns=2)
        for i in range(5):
            pre.record(USER if i % 2 == 0 else PERSONA, f"{handle}-t{i}")
    milo_ctx = ThreadTranscript(tmp_path, "milo", scope_for_space("spaces/AAA")).context(12)
    assert all("iris" not in m["content"] for m in milo_ctx)


def test_dm_and_room_contexts_never_cross(tmp_path):
    dm = ThreadTranscript(tmp_path, "milo", scope_for_space("spaces/DM111"))
    room = ThreadTranscript(tmp_path, "milo", scope_for_space("spaces/ROOM22"))
    dm.record(USER, "dm-only fact")
    room.record(USER, "room-only fact")
    assert [m["content"] for m in dm.context(12)] == ["dm-only fact"]
    assert [m["content"] for m in room.context(12)] == ["room-only fact"]


def test_conversation_and_compaction_never_write_shared_memory(tmp_path):
    reg = _registry("milo")
    comp = RecordingCompleter("noted")
    respond = remembering_responder(reg, comp, role="chat", memory_base=tmp_path)
    for i in range(3):
        msg = ChatMessage.from_text(f"m{i}", author="owner", is_owner=True, space="spaces/AAA")
        respond(Persona("milo", "Milo", "milo domain"), msg)  # 3 exchanges = 6 turns on disk
    # force a compaction through the SAME store the responder writes to (low test bounds)
    t = ThreadTranscript(tmp_path, "milo", scope_for_space("spaces/AAA"), max_turns=4, keep_turns=2)
    t.record(USER, "one more")  # 7 turns > 4 → folds oldest 5; summary Fact written
    assert t.summary() is not None
    # the shared tier reads the base directory — turns AND the summary stay in the private tree
    assert SharedMemory(tmp_path).all() == []
```

- [ ] **Step 2 — RED** (`test_responder_splices_summary_after_soul` fails: only one `system`
  message today). **Step 3 — implement:** the one-line `recent(history_turns)` →
  `context(history_turns)` change in `remembering_responder`; nothing else.
- [ ] **Step 4 — verify:** `uv run pytest tests/test_chat_memory.py -q` — every pre-existing #79
  responder/e2e test still green (signature and stateless/rollback semantics unchanged).
- [ ] **Step 5 — commit:** `feat(chat-memory): responder context = summary + window`

### Task 6 — [gated on #109] the transport seam: `build_responder` + `CLONWAY_CHAT_MEMORY_DIR`

**Blocked until `clonway-cockpit#109` is merged** (it creates `src/clonway_cockpit/chat_addon.py`
and `tests/test_chat_addon.py`). If unmerged at claim time: `agent:blocked`.
**Files:** modify `src/clonway_cockpit/chat_addon.py`; extend `tests/test_chat_addon.py`.
**Production call site (HR9):** `build_serve_app`'s `ChatRouter(responder=...)` construction —
replace the direct `gateway_responder(...)` call with
`build_responder(colleagues, gateway, role=role, memory_dir=...)`, `memory_dir` from
`CLONWAY_CHAT_MEMORY_DIR` (unset → `None`).

- [ ] **Step 1 — failing tests** (reuse `tests/test_chat_addon.py`'s `_call` helper from #109;
  define local copies of the `RecordingCompleter` class and a `_memreg(handle) -> ColleagueRegistry`
  helper mirroring `tests/test_chat_memory.py::_registry` — test modules do not import each
  other; duplicating a ≤10-line test helper is the house pattern):
  - `test_build_responder_memory_dir_selects_memory` — call
    `build_responder(reg, RecordingCompleter("noted"), role="chat", memory_dir=tmp_path)` twice
    via `respond(persona, ChatMessage.from_text(..., space="spaces/AAA"))`; second call's
    recorded messages == `["system", "user", "assistant", "user"]`; with `memory_dir=None` the
    second call is `["system", "user"]` (stateless) and `tmp_path` variant asserts turn files
    exist while the `None` variant leaves no files.
  - `test_build_serve_app_passes_memory_dir_env` — monkeypatch `chat_addon.build_responder` with
    a recording wrapper; build via the same env recipe as #109's
    `test_build_serve_app_wires_env_to_app` plus `CLONWAY_CHAT_MEMORY_DIR=str(tmp_path)`; assert
    the wrapper received `memory_dir == tmp_path`; unset → received `None`. (The selection
    *behaviour* is fully covered by the previous test; this pins the env plumb-through.)
  - `test_edge_dm_remembers_across_posts_with_memory_wired` — embed verbatim:

```python
def test_edge_dm_remembers_across_posts_with_memory_wired(tmp_path):
    reg = _memreg("milo")  # ColleagueRegistry helper mirroring test_chat_memory._registry
    comp = RecordingCompleter("noted")
    router = ChatRouter(
        registry=reg.registry,
        responder=remembering_responder(reg, comp, role="chat", memory_base=tmp_path),
        transport=FakeChatTransport(),
        allowlist=parse_allowlist("owner@clonway.example"),
    )
    app = build_addon_app(router, background=run_inline)
    for i, text in enumerate(["what are the Q2 figures?", "and Q3?"]):
        body = json.dumps(fake_dm_envelope(text, msg_id=f"m-{i}")).encode()
        assert _call(app, "POST", CHAT_EVENTS_PATH, body)[0] == "200 OK"
    # the REAL edge + REAL nested envelopes: POST 2's model call carries POST 1's exchange
    assert [m["role"] for m in comp.calls[1]] == ["system", "user", "assistant", "user"]
```

  - `test_edge_non_operator_dm_records_nothing_with_memory_on` — same app,
    `fake_dm_envelope("pay everyone now", email="evil@x.com", msg_id="m-evil")` → `200 OK`, zero
    transport posts, and `list(tmp_path.rglob("turn-*.md")) == []` (invariant row 13).
- [ ] **Step 2 — RED** (`ImportError: cannot import name 'build_responder'`),
  **Step 3 — implement:** `build_responder` per the contract table (import
  `remembering_responder` lazily or top-level — `chat_memory` is stdlib-only); `build_serve_app`
  reads `CLONWAY_CHAT_MEMORY_DIR` (env name defined once here, HR6) and passes `memory_dir`.
  When memory is on, the seen-store dedup #109 already wires is the mandatory redelivery guard
  `docs/thread-memory.md` requires — assert nothing extra is needed (the env test covers both
  set/unset with the store present).
- [ ] **Step 4 — verify:** `uv run pytest tests/test_chat_addon.py -q`. **Step 5 — commit:**
  `feat(chat-addon): CLONWAY_CHAT_MEMORY_DIR wires per-thread memory at the serve seam`

### Task 7 — [gated on #109] `--fake` REPL memory: `--memory-dir` + `EchoCompleter`

**Files:** modify `src/clonway_cockpit/chat_addon.py`; extend `tests/test_chat_addon.py`.
**Production call site (HR9):** `main()`'s `--fake` branch → `run_fake(..., memory_dir=...)`.

- [ ] **Step 1 — failing test:** `test_run_fake_with_memory_dir_carries_history` — call the
  merged `run_fake` with lines `["hi", "again"]` and `memory_dir=tmp_path`; assert the two
  replies are exactly `"[2 msgs] hi"` then `"[4 msgs] again"` (the worked example), and
  `tmp_path` contains 4 `turn-*.md` files under the demo persona's thread. Adapt the call to the
  merged `run_fake` signature (#109 pins its behaviour, not every kwarg) — record any adaptation
  in HANDOFF NOTES.
- [ ] **Step 2 — RED**, **Step 3 — implement:** `EchoCompleter` per the contract table; in the
  fake wiring, when `memory_dir` is set build a demo `ColleagueRegistry` (persona `demo`, soul
  `"You are Demo."`) and use
  `remembering_responder(demo_colleagues, EchoCompleter(), role="chat", memory_base=memory_dir)`
  instead of the stateless echo responder; add `--memory-dir` (type `Path`, default `None`) to
  `main()`'s parser, `--fake` only.
- [ ] **Step 4 — verify:** `uv run pytest tests/test_chat_addon.py -q`; manual smoke:
  `printf 'hi\nagain\n' | uv run python -m clonway_cockpit.chat_addon --fake --memory-dir /tmp/demo-mem`
  → second reply shows `[4 msgs]`. **Step 5 — commit:**
  `feat(chat-addon): --fake --memory-dir — local multi-turn with zero Google/model`

### Task 8 — docs, changelog, delivery table, full gates, RUNBOOK DELTA

**Files:** modify `docs/thread-memory.md` (bounds table, summary/compaction contract,
`forget` CLI, the env wiring, and prune the now-shipped "Scope & limits (v1)" items:
retention/compaction, atomic appends, whole-thread deletion), `docs/private-memory.md` (atomic
writes + `forget_thread`), `docs/chat-transport.md` (add `CLONWAY_CHAT_MEMORY_DIR` to the edge
env table #109 adds), `docs/persona-platform-architecture.md` (delivery table: add the row
`Bounded per-persona thread memory (window + compacted summary context, retention bounds, atomic writes, forget operation + CLI, serve/--fake wiring) — chat_memory.py + chat_addon.py | yes | yes | no | no | <this PR #>` —
per the table's own update rule; do NOT flip deployed/watched-working),
`docs/persona-platform-go-live-plan.md` (Slice C: bounded memory + wiring coded; remaining =
live deploy), `CHANGELOG.md` (`## [Unreleased]`), and this plan (tick boxes, HANDOFF NOTES).

- [ ] Docs + changelog updated as listed.
- [ ] Full gates, run verbatim from repo root, paste output tails in the DONE comment (HR2):
  `make lint` · `make format` · `make typecheck` · `make test`
- [ ] Post the `RUNBOOK DELTA` comment on `hearth-care/auto-orchestrator#196` (new operator
  surface: `CLONWAY_CHAT_MEMORY_DIR` deploy knob — must point at a durable mount, never Cloud
  Run `/tmp`; `--fake --memory-dir` local check; `python -m clonway_cockpit.chat_memory forget`
  deletion command) and repeat it in the DONE comment (HR1).
- [ ] **Commit:** `docs(thread-memory): bounded-memory contract, forget CLI, env wiring, changelog`

## OPERATOR TODO (not builder work)

1. When deploying the live edge (Slice B's OPERATOR TODO), set `CLONWAY_CHAT_MEMORY_DIR` on the
   service to a durable mounted path (persistent volume / GCSFuse — **not** `/tmp`, which is
   wiped on cold start → silent amnesia).
2. Keep the single-writer deploy shape (min-instances=1 / one background poster per space) — the
   same discipline `GcsCursorStore` documents; in-process concurrency is now safe (Task 2).

## Named follow-ups (out of scope here)

- Model-quality summarisation behind the same summary-Fact contract (swap the folding function).
- A GCS-API-backed thread store (only if a mount is ever unavailable).
- Retention *age* sweeps (delete threads idle > N days) — a policy decision for the operator
  first.

## Self-Review

- Spec coverage: contract table → Tasks 1–7; invariant rows 1–2 → Task 5, row 3 → Task 5, rows
  4–5 → Task 2, rows 6–8 → Task 3, row 9 → Task 4, rows 10 → Task 5, 11–12 → Task 1, 13 → Task
  6, 14 → existing regressions (named); every HR5 checkbox names its test.
- Safety invariants: 14-row cell table, one named test per row; durable-state partial-failure =
  folded-through authority + sweep recovery + idempotent forget (HR3/HR4); no money paths.
- Real contract: nested add-on envelopes only, via the merged core fixtures and #109's
  `fake_dm_envelope`; DM/ROOM strings per `NormalizedChatEvent.space_type` (HR12).
- Tests load-bearing: all assert replayed message lists, on-disk file sets, HTTP status +
  `transport.posted`, CLI stdout + directory absence — and each Step 2 names the expected RED
  (HR8).
- Wired end-to-end: compaction/context reach production via `remembering_responder` (Task 5) and
  the serve seam + REPL (Tasks 6–7); `forget` ships with its operator CLI call site — no dead
  helpers (HR9).
- Snippets: verified against `origin/main` @ `904e4ab` (`chat_memory.py`, `private_memory.py`,
  `shared_memory.py`, `group_chat.py`, `colleague.py`, `obs/atomicio.py`) and #109's binding
  plan for `chat_addon` names; constraints stated (`2 × DEFAULT_TURNS ≤ KEEP_TURNS <
  MAX_TURNS_ON_DISK`), no magic numbers without their rule (HR10); every pinned figure carries
  its arithmetic (compaction, truncation, next-index, REPL echo counts).
- Gates: `make lint` / `make format` / `make typecheck` / `make test`, verbatim (HR2).
- Operator-facing: yes (env knob + CLI + flag) → RUNBOOK DELTA checkbox in Task 8 (HR1).
- Dependencies: `[Wave 1]` + `Depends on: clonway-cockpit#109`; Tasks 1–5, 8 independent of it;
  no code wired to unmerged work outside the gated tasks (HR11).
- Deferred: the three named follow-ups; none block.

## HANDOFF NOTES

- Current phase: Task 3 complete (content-free unreadable-turn warning implemented; focused tests
  green).
- Next concrete step: commit/push Task 3, then start Task 4 forget-thread and CLI tests.
- Decisions taken: file-backed store + atomicio (no GCS-API store); deterministic extractive
  summarisation; folded-through authority in the summary Fact; next-index =
  `max([folded_through] + on_disk) + 1`; env-opt-in wiring at #109's seam.
- Known failing tests: none in `uv run pytest tests/test_chat_memory.py -q` after Task 3
  implementation (`39 passed` before commit).
- Dependencies/operator TODOs: #109 is merged into `origin/main` (verified 2026-07-02); OPERATOR
  TODO above remains for the live deploy.
