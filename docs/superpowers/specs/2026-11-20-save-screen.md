# Save screen and related screen fixes

**Status:** implemented in the branch that adds this file.

**Compatibility rule:** workers pin this library by release tag. No existing signature or
default changes; each new behaviour is opt-in through a keyword argument whose default keeps
today's output, except the single key-handling change in section 2, which only removes
accidental cancels.

## 1. The save step owns its screen

`walk.confirm_apply` gains `review: tuple[str, Sequence[str]] | None = None` and
`question: str = ""`. With `review` given, a terminal session draws a page itself: the title, the
lines, the question and a footer that names the keys exactly (`A or Enter saves · N or Esc
cancels`). Nothing on that page says "any key to return". In agent mode the same content goes out
as a `walk.review` frame ahead of the gate frame, with the key text in its metadata, so a driving
agent sees what it is asked to approve. Workers that pass no `review` see today's behaviour.

## 2. Keys at the save step

Enter, `a`, `A`, `y`, `Y` apply. `n`, `N`, Esc, `q`, `Q` decline. Any other key is ignored and the
step keeps waiting (it used to decline). The queued-keys flush before the read stays. Agent-mode
tokens and dry-run are untouched.

## 3. Note hint

`render_note` and `model_note` take `hint`, the header's right-hand text, defaulting to "any key to
return".

## 4. Link heading

The final walk screen's heading above links is a parameter (`links_heading`, default "view in
Xero") on `render_walk_result`/`model_walk_result`. A host sets its default once with
`Host.links_heading`, copied onto `WizardContext.links_heading`; a step may override per run with
`result_links_heading` in its result data.

## 5. Typed question drawn once

When the shell redraws the frame with the question, the line read beneath it uses only a cursor
marker (`▸ `). Multi-line questions stay whole inside the frame. When the walk drew its own screen
the prompt is passed through unchanged.

## 6. Shelf letters inside a shelf

In a shelf menu, another shelf's letter switches to that shelf. The menu's own item keys always
win, and a shelf's own letter does nothing.

## 7. Paging long results

When the outcome lines exceed the terminal rows less the frame's chrome (and the links block), a
terminal shows one page at a time with `page N of M · space for more · any other key to return`.
Agent mode still receives every line in one frame.

## 8. Doctor usage panel

`Host.show_usage` (default `True`) turns the "what you reach for" panel off when `False`.
