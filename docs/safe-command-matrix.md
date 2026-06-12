# Fleet safe-command matrix standard

> Owned by **clonway-cockpit**. Every worker in the fleet MUST publish a
> `docs/safe-command-matrix.md` in its own repo, conforming to this standard.
> See §[Adoption](#adoption) and §[Relationship to the cockpit write gate](#relationship-to-the-cockpit-write-gate).

---

## What this document is

A cross-fleet standard for answering, **before invocation**, whether a CLI
command is safe. Each worker repo publishes a `docs/safe-command-matrix.md`
that classifies every subcommand/flag combination it exposes against this
common vocabulary. An agent or operator can read any worker's matrix and know
immediately whether a command is safe to run, what it touches, and what they
will see first.

---

## The eight columns

Every row in a worker's matrix MUST populate all eight columns:

| Column | Required content |
|---|---|
| **Command** | Exact invocation shape — binary name, subcommands, flags. Use `<WORKER>` as the placeholder for the worker's own name. Use `(TTY)` / `(non-TTY)` suffixes when a bare invocation behaves differently depending on whether stdin/stdout is a real terminal. |
| **Help-only** | `✓` if this is the command's safety class (see §[Safety classes](#safety-classes)); blank otherwise. |
| **Read-only external** | `✓` if this is the command's safety class; blank otherwise. |
| **Local write** | `✓` if this is the command's safety class; blank otherwise. |
| **External draft** | `✓` if this is the command's safety class; blank otherwise. |
| **External post/apply** | `✓` if this is the command's safety class; blank otherwise. |
| **Credentials required** | Which credential, or `none`. Help-only rows MUST be `none`. Identify by role (`GCS service account`, `Gmail OAuth token`) not by secret name or env-var value. |
| **Expected first output** | What the caller sees on stdout/stderr before any blocking I/O or wait — a frame kind, a header line, or a prompt. Long enough to detect a hang or a surprise write immediately. |

Exactly one of the five safety-class columns MUST be `✓` in every row.

---

## Safety classes

The safety class is the **highest-impact behaviour** the command can reach in its
**default invocation** — meaning the invocation shown in the Command column, with
no extra environment variables set beyond the worker's normal runtime env.

| Class | Meaning | Permitted side-effects | Forbidden |
|---|---|---|---|
| **Help-only** | Prints usage / status and exits. No I/O beyond config reads. | Read env vars and local config files. Print to stdout. | Any network call; any credential hydration; any disk write outside config reads. |
| **Read-only external** | Reads external systems (APIs, GCS, databases) but mutates nothing. | Read live external state. Read and write local cache if listed by path. | Any mutation of an external system; any external draft or post. |
| **Local write** | Writes worker-local state or cache only; does not touch external systems. | Named local paths only (must be listed in the Expected first output or a note). | Any call that creates or mutates an artifact in an external system. |
| **External draft** | Creates a draft or pending artifact in an external system. The artifact is not yet visible as a completed action. | Create draft/pending external artifacts. | Finalise, post, or apply any external artifact; use the apply-gate token. |
| **External post/apply** | Mutates an external system in a way that is visible as a completed action. | Finalise external artifacts, write to shared stores (GCS fleet bucket, etc.), send messages, apply financial or HR actions. | Run without either the cockpit write gate (`confirm_apply`) or an explicit enabling flag. |

---

## Classification rules

Each rule is stated so that a reviewer can fail a **specific row** against it.

### R1 — One class per row

Every row has exactly one safety-class column marked `✓`. A row with zero or
more than one mark fails the matrix.

### R2 — Highest-impact wins

The class reflects the **highest-impact** behaviour reachable in the default
invocation, not the typical behaviour. A command that usually reads but can
write on a flag must use the write class.

### R3 — Name implies class (report/list/show/status commands)

Any command or subcommand whose name contains `report`, `list`, `show`, or
`status` MUST classify as **Help-only** or **Read-only external**. A
`status` subcommand that writes by default is a violation regardless of how
small the write is.

> Audit violation pattern: **report commands that default to write.**

### R4 — Dry-run must not write external; local writes must be named

A command described as "dry-run" MUST NOT mutate any external system. If it
writes local state (temp files, local cache, a local DB) it is not Help-only
— it is **Local write** at minimum, and every local path it writes MUST be
named in the row's Expected first output column or an inline note.

> Audit violation pattern: **dry-runs that write local state** (unlisted local
> paths beneath an apparent no-op).

### R5 — Help and bare invocations must be help-only; no credential hydration

`--help`, `-h`, and any bare invocation that prints usage MUST classify as
**Help-only**. These rows MUST carry `none` in Credentials required. A `--help`
path that resolves a credential, opens a network connection, or writes to disk
is a violation.

> Audit violation pattern: **help paths that hydrate secrets** (e.g. a
> `--help` that instantiates a client or reads a token file).

### R6 — External post/apply must name its gate

Every **External post/apply** row MUST identify in the Command column or a
note either (a) the cockpit write gate (`confirm_apply`) or (b) the explicit
enabling flag (env var name) that stands in front of the mutation. A row that
reaches an external post with neither is a violation.

### R7 — Matrix freshness

Adding, renaming, or removing a subcommand or flag without updating the
worker's own matrix fails the worker's PR checklist. The matrix is a
first-class deliverable, not a post-hoc annotation. See §[Adoption](#adoption).

---

## Relationship to the cockpit write gate

The cockpit write gate (`confirm_apply` / the dry-run + guarded-apply token
handshake) and this matrix are complementary, not redundant:

- **The gate covers cockpit walks.** Agent mode is dry-run by default;
  posting requires `serve_stdio(allow_apply=True)` plus a matched
  `{"apply":true,"token":…}` from the driver. This protects every
  capability registered in the cockpit.
- **The matrix covers the whole CLI surface.** Plain subcommands
  (`signals scan`, worker-specific report commands, provisioning helpers) sit
  outside the gate. That is exactly where fleet inconsistencies have been
  found, and where the matrix requirement applies.
- **Where they overlap, they must agree.** Any matrix row classified as
  **External post/apply** that is reachable through the cockpit MUST reference
  the gate or an equivalent explicit flag in its row. An External post/apply
  row with no gate reference is a violation of R6.

---

## Worked example — template scaffold command surface

The `worker-template/` generates a worker with the following command surface.
Every generated worker starts from this baseline; bespoke commands added to a
specific worker extend its own matrix.

`<WORKER>` = the worker's binary name (e.g. `xhr`, `xbook`).
`<EMIT_FLAG>` = `<WORKER_UPPER>_EMIT_SIGNALS` (e.g. `XHR_EMIT_SIGNALS`).

| Command | Help-only | Read-only external | Local write | External draft | External post/apply | Credentials required | Expected first output |
|---|:---:|:---:|:---:|:---:|:---:|---|---|
| `<WORKER> --help` | ✓ | | | | | none | `Usage: <WORKER> [OPTIONS] COMMAND [ARGS]...` |
| `<WORKER>` (non-TTY) | ✓ | | | | | none | `Usage: <WORKER> [OPTIONS] COMMAND [ARGS]...` |
| `<WORKER>` (TTY) | | | | | ✓ | all configured integrations (resolved per screen, lazy) | Rich three-region home panel (pulse / needs-you / toolkit) |
| `<WORKER> --agent-stdio` | | ✓ | | | | all configured integrations (resolved per screen, lazy) | `{"schema_version": …, "frame": "home", …}` (JSON, newline-delimited) |
| `<WORKER> --agent-stdio --allow-apply` | | | | | ✓ | all configured integrations + apply-gate token | `{"schema_version": …, "frame": "home", …}` (JSON, newline-delimited) |
| `<WORKER> signals scan` (`<EMIT_FLAG>` unset / `0`) | ✓ | | | | | none | `signals: disabled (set <EMIT_FLAG>=1 to enable)` |
| `<WORKER> signals scan` (`<EMIT_FLAG>=1`) | | | | | ✓ | GCS service account (`clonway-orchestrator-eu-west2`) | `signals: emitted N` |

**Notes:**

- `<WORKER>` (TTY) reaches External post/apply because the interactive cockpit
  exposes `confirm_apply`-gated capabilities that can finalise external
  actions. The write gate (R6) is satisfied: every capability in the cockpit
  goes through `confirm_apply` before any external mutation is reached.
- `<WORKER> --agent-stdio` is **Read-only external** because agent mode is
  dry-run by default — the guarded-apply token handshake is required for any
  write. Adding `--allow-apply` opts into that handshake, raising the class
  to External post/apply.
- `<WORKER> signals scan` with flag set writes to the shared GCS fleet bucket
  (`clonway-orchestrator-eu-west2`). The enabling flag (`<EMIT_FLAG>=1`) is
  the R6 gate: it is explicit, named, and defaults OFF.

---

## Adoption

**Every worker in the fleet MUST:**

1. Publish `docs/safe-command-matrix.md` in its own repo, with one row per
   CLI subcommand/flag combination, all eight columns populated, and exactly
   one safety-class column marked per row.
2. Start from the [template baseline](#worked-example--template-scaffold-command-surface)
   and extend it with every bespoke subcommand the worker adds.
3. Treat the matrix as a first-class deliverable: any PR that adds, renames,
   or removes a subcommand MUST update the matrix in the same change (R7).

The full column contract, safety-class vocabulary, and classification rules
are defined in this document. Workers do not invent new safety classes or
omit columns.
