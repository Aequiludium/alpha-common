# ygo Table Content Width Design

## Problem

`ygo top` stores display text and typed sort values in a `TableCell` Rich
renderable. Rich currently measures every `TableCell` as one terminal cell, so
Textual sizes `STARTED`, `GROUP`, and `COMMAND` from their headers instead of
their contents. Values are truncated even when horizontal scrolling could show
them.

## Design

Implement Rich's measurement protocol on `TableCell` and report the actual
terminal-cell width of its plain text. This preserves the existing typed sort
value while allowing Textual's auto-width columns to expand to the longest
value. Wide Unicode characters must use terminal-cell width rather than Python
character count.

When reconciliation changes an existing cell, call `DataTable.update_cell()`
with `update_width=True`. Textual will then expand or recompute that column when
content length changes. The table remains mounted and continues updating only
changed cells.

Columns may exceed the viewport. Textual's native horizontal scrolling is the
intended narrow-terminal behavior; values themselves are not capped or
truncated by ygo.

## Scope

No changes are made to task telemetry, sorting semantics, refresh frequency,
history persistence, or `show_progress`. Tests cover exact Rich measurement,
wide Unicode text, initial auto-sizing, and width updates for longer content.
