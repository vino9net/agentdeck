# MVP3: Search, Segmenter & Notifications

Depends on MVP2 (AgentOutputLog with FTS5, background capture).

---

## 1. Search API

Move `mode=search` from MVP2 to here. The FTS5 infrastructure
already exists in `AgentOutputLog.search()` — this step adds the
API endpoint and wires it to the frontend.

**Endpoint:**

```
GET /api/v1/sessions/{id}/output?mode=search&q=keyword
GET /api/v1/sessions/output?mode=search&q=keyword  (cross-session)
```

**Response:**
```json
{
  "results": [
    {
      "ts": 1738800000.0,
      "session_id": "agent-frontend",
      "snippet": "...matching <b>text</b>..."
    }
  ],
  "total_matches": 3
}
```

- Scoped to a session or cross-session (omit session_id)
- FTS5 ranking for relevance
- Snippets with match highlights via FTS5 `snippet()`

**Files:**
- `src/agentdeck/api/sessions.py` — add `mode=search` path

---

## 2. Search UI (chat-style layout)

Replace the removed Chat tab with a search-first interface that
displays results in a chat-style layout. This gives users a
natural way to browse agent interactions.

**Layout:**

```
┌──────────────────────────────────┐
│   [search query............]     │
├──────────────────────────────────┤
│                                  │
│  ┌──────────────────────┐        │
│  │ User prompt          │   ◀──  │  right-aligned (user)
│  └──────────────────────┘        │
│        ┌──────────────────────┐  │
│   ──▶  │ Agent response with  │  │  left-aligned (agent)
│        │ <b>matched</b> text  │  │
│        └──────────────────────┘  │
│                                  │
│  ── agent-frontend · 2h ago ──   │  session + time divider
│                                  │
│  ┌──────────────────────┐        │
│  │ Another user prompt  │   ◀──  │
│  └──────────────────────┘        │
│        ┌──────────────────────┐  │
│   ──▶  │ Tool call: Read      │  │  collapsible tool calls
│        │ file.py              │  │
│        └──────────────────────┘  │
│                                  │
└──────────────────────────────────┘
```

**Behavior:**
- Search bar at top, results stream below
- Each result shows the matching chunk in context
- Chat bubbles: user input right, agent text left
- Session dividers when results span multiple sessions
- Click a result to jump to that point in history scrollback
- DaisyUI `chat` component for bubble styling
- Empty state: recent activity feed (no query needed)

**Mobile:** Full-width bubbles, sticky search bar at top,
touch-friendly tap targets.

---

## 3. Segmenter + Structured Search

Parse raw log chunks into typed segments to power the chat-style
layout and enable filtered search.

**Segment types:** `user_input`, `agent_text`, `tool_call`,
`tool_result`, `system`

**Boundary detection:** Reuse existing regex from
`ui_state_detector.py` (`_HRULE_RE`, `_SPINNER_RE`). Indentation
changes mark tool result boundaries. Fallback: unmatched lines
append to current `agent_text` segment.

**Structured search:** Extend search API with `type` filter:
`?mode=search&q=auth&type=user_input`

**Schema change:**
```sql
ALTER TABLE chunks ADD COLUMN type TEXT;
```

**Files:**
- `src/agentdeck/history/segmenter.py` — line-by-line parser
- `src/agentdeck/history/models.py` — `SegmentType`, `Segment`
- `tests/test_segmenter.py` — use real tmux captures as fixtures

---

## 4. In-App Notifications

Detect when sessions need attention (stuck in PROMPT/SELECTION
state >3s). Show badges and update page title.

**Server-side:** Background task (reuse MVP2 capture loop) tracks
`_ui_states` and `_state_since` per session.

**API:** `GET /api/v1/sessions/notifications`
→ `[{session_id, state, seconds}]`

**Frontend:** Poll `/notifications` every 5s, update
`document.title` with count (`(2) agentdeck`), show badges
on session list items that need attention.

---

## Implementation Order

1. Search API endpoint (`mode=search`)
2. Basic search UI (search bar + raw result list)
3. Segmenter (parse chunks into typed segments)
4. Chat-style search results (bubbles, session dividers)
5. Structured search (type filter)
6. Notifications (server + frontend)

Steps 1-2 can ship independently of the segmenter. Steps 3-5
build on each other. Step 6 is independent.
