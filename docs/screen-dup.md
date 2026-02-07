# Screen-Boundary Duplication in History

## Status: Low priority — not a significant problem in practice

## Problem

The background capture loop captures scrollback every ~2s. Between
captures, the visible pane content can partially scroll up into the
scrollback buffer. When the next capture runs, the fingerprint dedup
(last 5 lines of previous capture) usually handles the overlap. But
edge cases can produce near-duplicate lines at capture boundaries:

1. **Exact pane-height burst**: output fills exactly one screen
   between captures. The previous fingerprint references lines that
   are now at a different position in the buffer.

2. **Repeated identical lines**: if the same line appears multiple
   times (e.g. blank lines, repeated log output), the fingerprint
   can match at the wrong position.

## Why it's low priority

- The scrollback-only capture approach already eliminates the main
  source of duplication (in-place spinner/progress updates).
- The `history_size` fast-path skips capture entirely when nothing
  has scrolled, which is the common case.
- When duplication does occur, it's a few lines at most — the
  content is still correct, just slightly repeated.
- History is a scrollback reference, not a precise transcript.
  Minor overlap doesn't affect usability.

## Possible future fixes

- **Increase fingerprint size** from 5 to 10+ lines. Reduces false
  matches but doesn't eliminate them.
- **Content-hash dedup**: hash each line and skip lines already
  stored. Adds complexity and doesn't handle legitimate repeated
  content well.
- **Sequence numbering**: if tmux exposed a monotonic line ID, we
  could deduplicate perfectly. It doesn't.

None of these are worth the complexity for the current use case.
