# xsource (Auto-Procurer) — design spec

**Date:** 10 June 2026 · **Status:** approved by owner (this document is the written form of that approval)
**Companion artifact:** [`2026-06-10-xsource-journey.html`](2026-06-10-xsource-journey.html) — a 12-frame high-fidelity walkthrough of the cockpit user journey. **Every frame is an acceptance target**: the built TUI should render like those frames, and the ☐ acceptance criteria in that file are part of this spec. Open it in a browser; it is self-contained.

This spec is deliberately exhaustive. It was produced at the end of a long design conversation with the owner and is written so that an implementer with **no access to that conversation** — and possibly a less capable model — can build the worker faithfully. Where a decision looks arbitrary, the reason is recorded. Do not relitigate decisions in §3 without new information; the research behind them is summarised in §15.

---

## 1. What this worker is

xsource is a new Clonway AutoWorker. The owner runs a small care business; ad-hoc procurement (an electrician, a plumber, a tree surgeon, a chipper to hire) is a recurring time sink that no staff member owns: someone has to find local providers, get prices, and pick one.

**The outcome xsource delivers:** the owner types a need in plain English ("a tree has come down across the back garden — need it chipped and removed this week"). Minutes later there is a pre-filled Google Sheet shortlisting ~5 local providers with ratings, contact details and indicative prices, plus drafted quote-request emails waiting in Gmail. The owner presses send. Supplier replies are parsed automatically onto the Sheet (quote amount, availability, summary). The owner marks the winner on the Sheet. A nightly sync files everything into a persistent supplier "black book" so the next request starts from institutional memory instead of Google.

**Identity:** `worker_id=xsource`, `worker_title="Auto-Procurer"`, package `xsource`, repo `~/Developer/Auto-Procurer`. Joins the fleet roster alongside xbook, xhr, xletter, xquill, xops.

## 2. How it is created — the factory

Generate the skeleton with copier from this repo (clonway-cockpit):

```
copier copy /Users/olliepage/Developer/clonway-cockpit ../Auto-Procurer
# prompts: worker_id=xsource · worker_title=Auto-Procurer · package_name=xsource
#          deploy_shape=local · clonway_rev=main
```

Validate with `make template-smoke` conventions; the generated repo ships CI (pytest/ruff/mypy), contract tests (`test_cockpit_render.py`, `test_cockpit_contract.py`, `test_signals_build.py`, `test_signals_emit.py`, `test_safety.py`), an `obs.py` telemetry shim, a `signals/` package with a mandatory `@scan_horizon` stub, and a typer CLI with a cockpit host. **All template contract tests must keep passing unmodified.** Follow `docs/onboarding-a-worker.md` in this repo for signals onboarding and `docs/agent-screen-model.md` for the agent protocol.

Framework abstractions you will use (all in `src/clonway_cockpit/`):

- `registry.py` — `CapabilitySpec(key, shelf, title, summary, run=walk_handler, blast_radius=…)`; register via `register_capability()`.
- `walk.py` / `shell.py` — step-based walks; the **single write gate** is `confirm_apply()`: dry-run by default, real side effects only behind a guarded-apply token + `--allow-apply`. Agent mode sees `ScreenModel(kind="walk.gate", meta={"gate":"awaiting_apply","token":…})`.
- `model.py` — `ScreenModel` JSON protocol (`schema_version="1.0"`), stable `Row.id`s; human Rich render and agent JSON are two projections of one screen, enforced by `assert_render_model_parity` and `assert_drives_clean`.
- `signals/` — `Signal(kind, title, detail, due_at, dedup_key, source_id)`; kinds used here: `action.required`, `deadline.approaching`, `anomaly.detected`. Emit to `gs://clonway-orchestrator-eu-west2/signals/xsource/latest.jsonl` (+ dated archive), flag-gated by `XSOURCE_EMIT_SIGNALS` (default OFF), empty `latest.jsonl` written on clean runs to clear stale sets.
- `gateway/` — `Gateway.complete_structured(messages, schema, role=…)` for the triage call. **Caveat:** the gateway's OpenAI-compatible adapter may not pass Anthropic's server-side web-search tool; see §8.4.

Register xsource in the xops roster: `/Users/olliepage/Developer/Auto-Orchestrator/src/xops/bridge/workers.py` — add `"xsource"` to `ROSTER` and `"auto-procurer": "xsource"` to `WORKER_ALIASES` (separate PR to that repo, phase 3).

## 3. Decisions log (owner-approved; do not reopen casually)

| # | Decision | Reason |
|---|----------|--------|
| D1 | Scope = research **+ drafted outreach**, never auto-send in v1 | Real quotes need outreach; owner keeps the send button. Auto-send is a deliberate phase-4 graduation behind the same write gate, not a config flip. |
| D2 | Persistent **black book**, worker-owned store | Compounds in value; enables recurring-service signals ("boiler service due — last used Smith Heating, £180"). |
| D3 | Black book canonical store = **JSONL in GCS**, not a human-edited Sheet | Lesson from the owner's occupancy tracker: sheets humans edit drift layout and silently break readers. Sheets are *views* and bounded *forms*, never the canonical store. |
| D4 | Discovery = Places API + site-targeted LLM web search (incl. directories) + Companies House cross-check | See §15. No Yell/Checkatrade scrapers: Yell has no API and prohibits automated copying; Checkatrade's partner API is lead-submission only. Site-targeted web search reads their public listings the way a human searcher does. |
| D5 | Trigger = **cockpit walk** day one | Cheapest path through the factory; email/chat triggers are phase 4. |
| D6 | Codename **xsource** | Owner's pick over xbuy/xprocure. |
| D7 | **The Google Sheet is the operator surface** for the request lifecycle | Owner: "the presentation layer of this tool is the Google sheet." Outreach status, replies, quotes, the decision — all live there. The TUI is the engine room (fire requests, browse the black book, doctor). **No TUI data entry is ever required to close the loop.** |
| D8 | Outreach + reply parsing **reuse Auto-Secretary's milo machinery** | Owner: reuse existing technology. milo already has the poll daemon, idempotency store, stance+constitution prompt composition, provenance dumps, and a draft-only safe client. Build no parallel email stack. |
| D9 | Reply identification = **Gmail `threadId` captured at draft creation** | No subject-line reference numbers. Structural, not cosmetic. Off-thread replies handled by a low-confidence sender-match fallback that flags for review, never auto-parses. |
| D10 | Sheet observability = per-row **Updated** stamp + header **heartbeat** | Owner: detect "email received but never landed on the sheet". Two timestamps decompose the failure: fresh heartbeat + stale row = parse bug; stale heartbeat = watcher down. |
| D11 | Spec + walkthrough live in clonway-cockpit; worker code in its own generated repo | The factory owns worker designs until the worker repo exists. |

## 4. Operating model (one paragraph to hold in mind)

The TUI fires a request and shows health. The Sheet is where the request *lives*: the worker writes discovery results and parsed replies into it; humans write the decision and notes into it; a nightly sync extracts the human columns into the black book store. The watcher daemon (milo pattern) bridges Gmail threads to Sheet rows. Signals surface anything that needs chasing. Everything that mutates the outside world (Sheet creation, Gmail drafts, store writes during a walk) passes through the framework's single write gate.

## 5. Capabilities (cockpit shelf)

| Key | Shelf letter | What it does | Blast radius |
|---|---|---|---|
| `request.new` | A | The main walk: need → triage → research → review → apply (sheet + drafts + store + arm watcher) | writes (gated) |
| `request.list` / `request.view` | B | Open/closed requests; view opens a card with sheet link, thread states | read-only |
| `book.search` / `book.view` | C | Browse black book; card shows history, notes, preferred; `[n]` add note, `[p]` toggle preferred (conveniences, never required) | mostly read |
| `book.publish` | D | Render read-only supplier directory Sheet for staff; idempotent, regenerable | writes (gated) |
| `book.import` | C (sub) | One-off seed from CSV/Sheet of the owner's existing black book | writes (gated) |
| `request.sync` | B (sub) | On-demand version of the nightly Sheet→store sync | writes (gated) |
| `watcher.status` | B (sub-card; also a doctor probe) | The reply-watcher card (journey frame 10): threads watched, last poll, parses | read-only |
| `signals scan` | CLI | Standard template command | emits JSONL |

Walk-step structure for `request.new` (5 steps, matching journey frames 02–07): preflight → need entry → triage confirm → staged research → review/apply.

## 6. Data model

Store: worker-owned JSONL at `gs://clonway-orchestrator-eu-west2/state/xsource/` — `suppliers.jsonl`, `requests.jsonl`. Single operator ⇒ single writer; read-modify-write whole file is acceptable at this scale (hundreds of records). Keep a local cache for offline reads; offline degrades to read-only with a warn pill. Corrupt lines are quarantined with a warning, never a crash. Round-trip property test required (upsert → reload → identical).

```jsonc
// Supplier
{
  "id": "s-0017",                      // stable, assigned once
  "name": "Westcountry Tree Care",
  "categories": ["trees-grounds"],      // kebab-case taxonomy, grow as needed
  "tags": ["tree-surgery", "chipping"],
  "phone": "+441626332...",             // E.164 normalised
  "email": "info@westcountrytreecare.co.uk",
  "website": "westcountrytreecare.co.uk",
  "address": "...", "postcode": "TQ12 ...",
  "place_id": "ChIJ...",                // Google Places, when sourced there
  "rating": {"google": [4.9, 31], "yell": null, "checkatrade": null},  // [score, review_count]
  "source": "places",                   // places|yell|checkatrade|web|companies_house|manual|import
  "source_url": "https://...",          // listing/profile provenance
  "companies_house": {"number": "...", "sic": ["81300"], "incorporated": "2019-04-01"},  // nullable
  "preferred": true, "preferred_set": "2024-10-12",
  "first_seen": "2024-10-01", "last_used": "2024-10-12",
  "price_history": [ {"date": "2024-10-12", "job": "fallen branch, front drive", "amount": 220, "outcome": "used"},
                     {"date": "2026-06-11", "job": "tree chipping r-0042", "amount": 190, "outcome": "quoted"} ],
  "notes": [ {"date": "2024-10-12", "by": "owner", "text": "fast, tidy, took the logs away"} ],
  "recurs_every_months": null           // e.g. 12 for boiler service → deadline.approaching signal
}

// Request
{
  "id": "r-0042",
  "created_at": "2026-06-10T15:58:00+01:00",
  "raw_need": "A tree has come down across the back garden at Rowan House...",
  "triage": { "category": "trees-grounds", "search_terms": [...], "also_try": [...], "email_vars": {...} },
  "constraints": { "radius_miles": 15, "needed_by": "2026-06-13", "budget": null, "shortlist_n": 5 },
  "status": "open",                     // open|quoted|chosen|closed|cancelled
  "sheet_id": "1AbC...", "sheet_url": "https://docs.google.com/...",
  "indicative_range": {"low": 150, "high": 400, "sources": 3},
  "shortlist": [
    { "supplier_id": "s-0017", "rank": 1, "indicative": [150, 250],
      "outreach": { "mode": "email",            // email|call
                    "draft_id": "r-...", "thread_id": "18c9...",   // thread_id captured AT DRAFT CREATION
                    "asked_at": "2026-06-10T16:02:00+01:00",       // set by watcher sent-detection
                    "last_reply_at": null },
      "reply": { "summary": null, "quote": null, "availability": null, "raw_msg_ids": [] },
      "excluded": false }
  ],
  "chosen_supplier_id": null,
  "watcher": { "armed": true, "last_poll": "2026-06-11T09:42:00+01:00" }
}
```

## 7. The Sheet contract (journey frame 09 — pin with a golden-file test)

One spreadsheet per request, title `Procurement — <short need> — <d Mmm>`, created in the `Procurement/` Drive folder, shared with the configured staff group on creation. One data tab. Fixed columns **in this exact order**:

`# · Provider · Source · Rating · Phone · Email · Indicative · Status · Asked · Reply · Quote £ · Chosen · Updated · Notes`

- **Worker-written:** Provider, Source (hyperlinked to listing/profile provenance), Rating (native scale: Google ★0–5, Yell ★0–5, Checkatrade 0–10), Phone, Email, Indicative, Asked, Reply, Updated; Status auto-flips `Draft ready → Asked` (watcher sees the draft sent) `→ Replied/Quoted` (reply parsed).
- **Human-edited:** Chosen, Notes, plus Quote £ and Status for phone quotes. Status is data-validated to: `To call / Draft ready / Asked / Replied / Quoted / Chosen / No`.
- **Updated** is stamped in the same batch update as any worker write to that row — a row can never change without its timestamp changing.
- **Heartbeat:** the header/title bar carries `xsource last checked HH:MM`, advanced on every poll cycle with live threads, throttled to hourly when idle (keeps revision history sane).
- A footer row carries: job description, location, needed-by, indicative range, and `request r-0042` (traceability back to the store).
- Conflict rule (deterministic, no merge UI): **human columns — sheet wins; worker columns — store wins.** Status auto-flips yield to a human-set value.

## 8. Discovery pipeline (`request.new` step 4; journey frame 05)

Stage order, each an independently failing stage (`⚠ skipped` degrades, run completes from the rest):

1. **black book** — match suppliers by category/tags; matches rank first and are shown at triage.
2. **Google Places** — Text Search + Place Details within `radius` of `XSOURCE_HOME_POSTCODE`. Fields: name, rating, review count, phone, website, address, place_id.
3. **directories** — site-targeted web search: queries like `site:yell.com tree surgeon Newton Abbot`, `site:checkatrade.com tree surgeon TQ12`. ~2–4 searches per run across both directories.
4. **web sweep** — open web search for indicative price ranges ("typical cost tree removal Devon") and review-less locals (parish/Facebook mentions).
5. **rank & dedupe** — merge + Companies House cross-check.

### 8.1 Directory parsing — the model is the parser, a schema and a validator are the contract

No CSS selectors, no per-site templates (site redesigns must not break anything). Three steps:

1. **Search** (site-targeted, via the web-search tool) — the search index finds listing pages; we read what a searcher would.
2. **Extract** — structured output against a fixed candidate schema; *every candidate requires `source_url`; every field nullable*; instruction: "report only what the listing actually shows; leave anything else null."
   ```jsonc
   { "candidates": [ { "name": str, "phone": str|null, "email": str|null,
       "profile_url": str,            // REQUIRED
       "rating": number|null, "review_count": int|null,
       "town": str|null, "categories": [str], "source_quote": str  // verbatim span the data came from
   } ] }
   ```
3. **Validate in plain code** before anything reaches the shortlist: `profile_url` domain must match the targeted directory; phone must normalise as valid UK (E.164); rating within native bounds (Yell 0–5, Checkatrade 0–10); then dedupe vs Places (normalised phone / website domain / fuzzy name ≥ threshold). Failed fields are nulled; failed candidates dropped. **Unit tests pin the validator and schema with recorded fixtures — never exact LLM output** (it is non-deterministic).

### 8.2 Companies House cross-check (demoted to ranking, not a headline stage)

Free REST API. Use for: legitimacy ("incorporated 2019", flag dissolved companies on the shortlist), and occasionally surfacing incorporated trades with zero web presence (advanced search by SIC + registered-office postcode; SIC codes: 43220 plumbing/HVAC, 43210 electrical, 81300 landscape/tree work, 77320 plant hire). Limits, stated honestly: misses sole traders, no contact details/ratings, registered office ≠ trading area. CH-only candidates appear as "exists, registered — find number / call to assess".

### 8.3 Ranking

`black-book history > rating × review-volume (native scales normalised) > proximity`. Top `shortlist_n` (default 5) survive to review. Cross-listed firms merge with all provenance kept.

### 8.4 The web-search seam (implementation trap)

Anthropic's web search is a **server-side tool**; the framework Gateway's OpenAI-compatible adapter may not pass it through. Put all search-and-extract calls behind `src/xsource/research/websearch.py`; inside, call the `anthropic` SDK directly if the Gateway cannot (precedent: xbook's `milo_demo.py` imports `anthropic.Anthropic()` raw). Nothing outside that module may know which path was taken. Verify current model id and web-search tool pricing from the claude-api skill / docs at build time — do not hardcode guesses.

### 8.5 Honest-data rule (global AC)

No fabricated contact details, ratings, prices, or quotes — every shortlist/Sheet cell traces to a source (`book/maps/yell/chk/web/CH`) or renders `—`. Indicative ranges always cite source count. Parsed quotes require a verbatim source span (§10).

## 9. Outreach — reuse milo (journey frames 06–08)

milo lives at `/Users/olliepage/Developer/Auto-Secretary/xquill/milo/` and is the **pattern source**; read it before building:

- `daemon.py` — `run_milo_cycle()`: 60s poll loop, idempotency via SQLite `processed_messages`.
- `handler.py` — `handle_forward()`: parse → find thread → cap context → draft → post → audit.
- `safe_milo.py` — `SafeMiloClient`: the safety boundary; **no send method exists on the class**.
- `state.py` — SQLite idempotency store. Provenance dumps: full diagnostic JSON per handled message under `~/.claude-inbox/milo/provenance/`.
- Prompt composition: `clonway_cockpit.persona_soul.compose_system_prompt(soul)` stacks a stance file on the shared constitution (guardrails are validated in, cannot be removed by a custom stance).

What xsource builds from those parts:

- **`SafeOutreachClient`** (sibling of `SafeMiloClient`): exposes `create_draft(to, subject, body, label)` **only**. The Gmail API returns the draft's `threadId` at creation — persist it on the request's shortlist entry **before anything is sent** (D9). Drafts are created in `milo.garth@clonwaycare.co.uk`'s mailbox under label `xsource/outbox`. CI grep gate: no call sites for `drafts.send`/`messages.send` anywhere in the xsource package.
- **Procurement `stance.md`**: the owner's voice for quote requests — brief, courteous, concrete: what the job is, where (town only — full address comes later by phone), when it is needed, ask for a price and earliest availability, and a quiet `ref r-0042` in the body footer (helps the off-thread matcher and phone follow-ups; **never** in the subject line).
- Drafting via `compose_system_prompt(procurement_stance)` + the triage `email_vars`; one draft per shortlisted supplier with an email. Provenance dump per draft under `~/.claude-inbox/xsource/provenance/`.
- milo's own forward-handling path is **untouched**: xsource never reads milo's forwards; milo's operator whitelist never sees suppliers. They share a mailbox and parts, not a loop.

## 10. Reply watcher (journey frame 10)

xsource's own daemon, same skeleton as `run_milo_cycle` (poll `XSOURCE_POLL_SECONDS=60`, SQLite idempotency, provenance dump per parse):

- **Primary watch — thread-id-bounded:** poll exactly the stored `thread_id`s of open requests. New message on a watched thread from a non-us sender ⇒ supplier reply ⇒ parse. The watcher never scans or classifies the wider inbox (privacy property + can't misfile).
- **Sent-detection:** our own message appearing on a thread flips that row's Status to `Asked` + stamps `asked_at`. Nothing to record manually.
- **Parsing:** structured extraction — `{quote_amount: number|null, currency, includes: str|null, availability: str|null, conditions: str|null, declined: bool, summary: str (≤1 line), source_span: str (verbatim REQUIRED for quote_amount)}`. **No-fabrication rule:** `Quote £` fills only when a number was actually quoted (schema requires the verbatim span); ambiguous replies become Status `Replied` + summary; declines map to Status `No`.
- **Sheet write:** one batch update — Reply summary, Quote £ (if any), Status flip, row `Updated` stamp. Then update the request record.
- **Off-thread fallback (low confidence):** secondary pass over recent messages whose sender address/domain matches a shortlisted supplier on an open request ⇒ flagged as "possible reply — needs a look" (needs-you item + request card), **never auto-parsed**, because the match is inferred not structural.
- **Heartbeat:** advance the Sheet header `xsource last checked HH:MM` per active poll cycle (hourly throttle when idle).
- **Health:** watcher stale >2h with live threads ⇒ home pill `◐` + `anomaly.detected` signal. Diagnostic triple (reply present + heartbeat fresh + row stale beyond one poll) must be reproducible in an integration test and point at the provenance file.

## 11. Sheet → black book sync (journey frame 11)

Nightly (launchd) + on-demand walk `request.sync`. Reads only human-editable columns back. Per open request:

- `Chosen ✓` on a row ⇒ request `closed`; winner's `last_used` + `price_history` (`outcome:"used"`) stamped; losers' quotes kept as `price_history` (`outcome:"quoted"`); needs-you and chase signal cleared; sheet archived (link kept on the request record).
- Quote £ / Status / Notes edits ⇒ request shortlist + supplier notes updated.
- Idempotent (re-run is a no-op) and drift-tolerant: renamed/moved column ⇒ warn and skip, never mis-file. Unknown rows ⇒ warn, never crash.
- Conflict rule as §7: human columns sheet-wins, worker columns store-wins.

## 12. Signals (`@scan_horizon`, three builders — all pure functions of (today, now) + store)

| Builder | Kind | Fires when | dedup_key |
|---|---|---|---|
| chase-quotes | `action.required` | open request with outstanding asks after N days (default 3), urgency sharpened by `needed_by` | `xsource\|chase\|r-0042` |
| recurring-service | `deadline.approaching` | supplier `recurs_every_months` due within 21d | `xsource\|recur\|s-0017` |
| watcher-health | `anomaly.detected` | watcher stale >2h with live threads | `xsource\|watcher` |

Unit-test matrix (minimum): fresh request → none; 3-day unanswered → chase; all-quoted → none; recurs due in ≤21d → deadline; watcher stale → anomaly. Emission honours `XSOURCE_EMIT_SIGNALS` default-OFF and writes empty `latest.jsonl` on clean runs.

## 13. Config, secrets, costs, deployment

- **Config:** `XSOURCE_HOME_POSTCODE`, `XSOURCE_DEFAULT_RADIUS_MILES=15`, `XSOURCE_SHORTLIST_N=5`, `XSOURCE_POLL_SECONDS=60`, `XSOURCE_CHASE_AFTER_DAYS=3`, caps `XSOURCE_MAX_PLACES_CALLS=10`, `XSOURCE_MAX_WEB_SEARCHES=8` (per run), `XSOURCE_MONTHLY_BUDGET_GBP=10`, staff share group, Drive folder id.
- **Secrets (Secret Manager, loaded at startup; none in code):** Google Maps Platform key (Places API (New)); Anthropic API key (research role); Drive/Sheets OAuth token; reuse of milo.garth Gmail OAuth for `SafeOutreachClient` + watcher (compose/read as needed — keep xhr's `gmail.readonly` invariant on *xhr's* token untouched; xsource has its own).
- **Costs:** Places text search ≈ pennies/call with a monthly free tier; Anthropic web search ≈ $10/1k searches + tokens. `[ASSUMPTION — verify both price sheets at build time; do not hardcode]`. Per-run cost estimate shown live on the research screen and written to obs telemetry (xops `model_spend` picks it up). Budget pill on Home: `◐` at 75% of monthly cap, `✗` + block new research walks at 100%.
- **Deployment:** `deploy_shape=local`. Interactive runs in the cockpit on the Mac. launchd jobs (xquill precedent — see xquill's plist): watcher daemon, nightly sync, daily `signals scan` with `XSOURCE_EMIT_SIGNALS=1`. Cloud Run promotion only if ever needed.
- **Telemetry:** obs JSONL to `gs://clonway-orchestrator-eu-west2/logs/xsource/…`; gateway telemetry stays content-free (no PII off-box).

## 14. Testing strategy

- Template contract tests pass unmodified (render/model parity, drives-clean, write-gate, signals flag/degrade).
- Pure-function units: ranking, dedupe, validators (recorded fixtures), signal builders (matrix §12), sheet template golden file, store round-trip property test, sync idempotency + drift cases.
- Triage: mocked gateway, schema validation, malformed-output retry → clean `✗` failure with no partial state.
- Watcher: idempotency (re-run no-op), thread-bounded reads, reply-classification matrix (quoted-with-number / replied-no-number / decline), off-thread fallback flags-not-parses, provenance file per parse, diagnostic-triple integration test.
- Write gate: dry-run drive of every walk leaves the world untouched (extend `test_safety.py` to all three side effects); CI grep gate for Gmail send endpoints.
- Live integration smokes behind env flags (real Places/CH/Sheets/Gmail), not in CI.
- Before operator hand-off: run the **final-boss-audit** skill; the journey HTML's ☐ boxes are the audit checklist; the acceptance head must drive every screen (no dead controls).

## 15. Research findings behind D4 (verified June 2026; cite, don't re-research)

- **Yell**: developer portal dead (ECONNREFUSED); no API; ToS prohibit automated monitoring/copying. Third-party scrapers exist (Apify ~$30/mo) — rejected (ToS violation at one remove, fragile).
- **Checkatrade**: real partner API at developers.checkatrade.com but it is **lead submission** (`POST /jobs`, HMAC auth, partner agreement) — you get matched trades back only by creating a real consumer lead. Parked as **phase 4** ("post the job, vetted trades respond") — write-gated if ever built, since it creates real leads.
- **MyBuilder / Rated People / Bark / Which? Trusted Traders / TrustATrader**: no viable programmatic surface (TrustATrader has an undocumented per-trader JSON endpoint — too fragile to depend on).
- **SerpAPI / DataForSEO**: no Yell/Checkatrade products.
- **Bing Search APIs retired Aug 2025**; Foursquare weak on UK one-man trades; OSM coverage of small trades sparse (skipped, YAGNI).
- **Companies House**: free REST + bulk; great for incorporated-trade existence/legitimacy; misses sole traders; no contacts/ratings → demoted to cross-check (D4/§8.2).

## 16. Phasing

| Phase | Ships | Journey frames |
|---|---|---|
| **P1 Research** | Scaffold, store + import/seed, `request.new` through to the Sheet (no outreach), doctor probes, book browse/publish | 01–06, 08–09 (sheet only), book card |
| **P2 Outreach** | milo-engine drafts (procurement stance, `SafeOutreachClient`, threadId capture) behind the write gate, outbox label | 06–08 complete |
| **P3 Hands-free loop** | Reply watcher (sent-detection, parse-to-sheet, off-thread fallback, heartbeat), nightly sync + `request.sync`, all three signals, launchd, xops roster | 10, 11, 12, Home needs-you |
| **P4 Later (not now)** | Auto-send graduation (write-gated), follow-up drafting, email/chat trigger, Checkatrade affiliate API | — |

Each phase is independently shippable and demonstrable to the owner.

## 17. Gotchas for implementers (hard-won; read twice)

1. **Gmail `threadId` is returned at draft creation** — capture it then, not at send. The sent message stays on the same thread.
2. **milo's whitelist will reject suppliers by design** — do not try to route supplier replies through milo's forward handler; build the sibling watcher.
3. **The Gateway may not pass server-side web-search tools** — seam at `research/websearch.py`, anthropic SDK direct fallback (§8.4).
4. **Never test exact LLM output** — pin schemas and validators with fixtures.
5. **Sheets humans edit drift** — that is why the store is canonical, the template is golden-file-pinned, Status is data-validated, and sync warns-and-skips on drift.
6. **No emoji in the TUI**; follow the framework palette exactly (amber `#d18d54`, blue `#7a9cc6`, ok `#7faa7f`, err `#e06c6c`, braille spinner, `❯`/`▸` glyphs). The journey HTML is the render reference.
7. **Worker repo conventions:** claude/* branches, no Co-Authored-By trailers, full pytest in CI not pre-commit, `.claude/worktrees/` gitignored.
8. **Don't put the reference number in the subject line** — body footer only (D9).
9. **Rating scales differ** (Google/Yell 0–5, Checkatrade 0–10) — store native, display native, normalise only inside ranking.
10. **Apply is atomic-ish with honest failure:** if drafts succeed and the sheet fails, say exactly what exists; capture partial state for retry; never a silent half-success.
