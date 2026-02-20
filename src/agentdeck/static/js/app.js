/* Alpine.js component for agentdeck */
document.addEventListener("alpine:init", () => {
  Alpine.data("codeServer", () => ({
    activeSession: null,
    inputText: "",
    connected: false,
    sessions: [],
    recentDirs: [],
    newTitle: "",
    newWorkingDir: "",
    newAgentType: "claude",
    uiState: "working",
    selectionItems: [],
    selectedIndex: 0,
    selectionQuestion: "",
    slashCommands: [],
    _snippetsConfig: { global: [], directories: {} },
    showDebugModal: false,
    debugDescription: "",

    // Attach button long-press popover
    _attachPopoverOpen: false,
    _attachLongPressTimer: null,
    _attachLongPressed: false,

    // Slash-command nav mode
    _slashNav: false,

    // Push notification state
    _pushSubscription: null,
    _notifiedSessions: new Set(),
    _publicUrl: "",

    // History scrollback state
    _nearTop: true,
    _scrollFar: false,
    historyChunks: [],
    earliestTs: null,
    historyLoading: false,
    historyExhausted: false,
    _historyObserver: null,
    scrollTimestamp: "",
    _scrollTsTimer: null,

    // Computed-style getters
    get aliveSessions() {
      return this.sessions.filter((s) => s.is_alive);
    },
    get deadSessions() {
      return this.sessions.filter((s) => !s.is_alive);
    },
    get isActiveSessionAlive() {
      if (!this.activeSession) return false;
      const s = this.sessions.find(
        (s) => s.session_id === this.activeSession
      );
      return s ? s.is_alive : false;
    },
    get sessionCount() {
      return this.aliveSessions.length;
    },
    get activeSessionInfo() {
      if (!this.activeSession) return null;
      return this.sessions.find(
        (s) => s.session_id === this.activeSession
      ) || null;
    },
    get buttonLayout() {
      if (this._slashNav) return "slash";
      if (this._scrollFar) return "scroll";
      if (
        this.uiState === "selection" &&
        !this._selectionDismissed
      )
        return "selection";
      return "normal";
    },
    get promptSnippets() {
      const g = this._snippetsConfig.global || [];
      const info = this.activeSessionInfo;
      const dir = info?.working_dir;
      const dirs = this._snippetsConfig.directories || {};
      const d = dir && dirs[dir] ? dirs[dir] : [];
      return [...g, ...d];
    },
    get notificationsSupported() {
      if (!("PushManager" in window)) return false;
      if (!("serviceWorker" in navigator)) return false;
      if (!this._publicUrl) return false;
      return window.location.origin === this._publicUrl;
    },
    get isSessionNotified() {
      if (!this.activeSession) return false;
      return this._notifiedSessions.has(this.activeSession);
    },

    formatEndedAt(ts) {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      const mon = d.toLocaleString(undefined, { month: "short" });
      const day = d.getDate();
      const h = d.getHours().toString().padStart(2, "0");
      const m = d.getMinutes().toString().padStart(2, "0");
      return `${mon} ${day} ${h}:${m}`;
    },

    formatChunkTs(ts) {
      if (!ts) return "";
      const d = new Date(ts * 1000);
      const age = Date.now() / 1000 - ts;
      const h = d.getHours() % 12 || 12;
      const m = d.getMinutes().toString().padStart(2, "0");
      const ampm = d.getHours() < 12 ? "AM" : "PM";
      if (age < 43200) {
        const s = d.getSeconds().toString().padStart(2, "0");
        return `${h}:${m}:${s} ${ampm}`;
      }
      const mon = d.toLocaleString(undefined, {
        month: "short",
      });
      const day = d.getDate();
      return `${mon} ${day} ${h}:${m} ${ampm}`;
    },

    timeAgo(ts) {
      if (!ts) return "";
      const seconds = Math.floor(Date.now() / 1000 - ts);
      if (seconds < 60) return "just now";
      const minutes = Math.floor(seconds / 60);
      if (minutes < 60) return `${minutes}m ago`;
      const hours = Math.floor(minutes / 60);
      if (hours < 24) return `${hours}h ago`;
      const days = Math.floor(hours / 24);
      return `${days}d ago`;
    },

    init() {
      // Resize container to visual viewport so it stays
      // above the mobile software keyboard.
      if (window.visualViewport) {
        const setAppHeight = () => {
          document.documentElement.style.setProperty(
            "--app-height",
            `${window.visualViewport.height}px`
          );
          // Re-pin scroll after viewport shrinks (keyboard open)
          if (this._pinned) {
            requestAnimationFrame(() => {
              const t = this.$refs.terminalScroll;
              if (t) t.scrollTop = t.scrollHeight;
            });
          }
        };
        window.visualViewport.addEventListener(
          "resize",
          setAppHeight
        );
        setAppHeight();
      }

      // Track connection state via HTMX polling results
      document.addEventListener("htmx:afterRequest", (evt) => {
        const tc = document.getElementById("terminal-container");
        if (!tc || !tc.contains(evt.detail.elt)) return;
        this.connected = evt.detail.successful;
      });

      // Auto-scroll: pin to bottom unless user scrolls up.
      this._pinned = true;
      this.$nextTick(() => {
        const target = this.$refs.terminalScroll;
        if (!target) return;

        let lastClientH = target.clientHeight;
        target.addEventListener("scroll", () => {
          const gap =
            target.scrollHeight -
            target.scrollTop -
            target.clientHeight;
          const resized =
            target.clientHeight !== lastClientH;
          lastClientH = target.clientHeight;
          // Skip _pinned update on resize-triggered
          // scrolls (keyboard open/close, textarea
          // shrink) and manual prompt jumps.
          if (this._jumpGuard) {
            this._jumpGuard = false;
          } else if (!resized) {
            this._pinned = gap < 50;
          }
          this._nearTop = target.scrollTop < 100;
          this._scrollFar =
            gap > target.clientHeight * 2;
          this._updateScrollTimestamp(target);
        });

        target.addEventListener("wheel", (e) => {
          if (e.deltaY < 0) this._pinned = false;
        });

        const observer = new MutationObserver(() => {
          if (this._pinned && !this.historyLoading) {
            requestAnimationFrame(() => {
              target.scrollTop = target.scrollHeight;
            });
          }
        });
        observer.observe(target, {
          childList: true,
          characterData: true,
          subtree: true,
        });
      });

      // Read UI state after each HTMX poll settles
      this._selectionDismissed = false;
      document.addEventListener("htmx:afterSettle", (evt) => {
        const tc = document.getElementById("terminal-container");
        if (!tc || !tc.contains(evt.detail.elt)) return;
        const el = document.getElementById("ui-state-data");
        if (!el || !el.dataset.state) return;
        try {
          const data = JSON.parse(el.dataset.state);
          if (data.state !== "selection") {
            this._selectionDismissed = false;
          }
          if (data.state === "selection" && this._selectionDismissed) {
            // Keep items updated but don't switch UI back
            this.selectionItems = data.items || [];
            this.selectedIndex = data.selected_index || 0;
            this.selectionQuestion = data.question || "";
            return;
          }
          this.uiState = data.state || "working";
          this.selectionItems = data.items || [];
          this.selectedIndex = data.selected_index || 0;
          this.selectionQuestion = data.question || "";
        } catch {
          // Ignore parse errors
        }
      });

      const initialSessions = this.$el.dataset.sessions
        ? JSON.parse(this.$el.dataset.sessions)
        : [];
      this.sessions = initialSessions;
      this._snippetsConfig = this.$el.dataset.snippets
        ? JSON.parse(this.$el.dataset.snippets)
        : { global: [], directories: {} };
      this.refreshSessions();
      this.refreshRecentDirs();
      this.refreshSlashCommands();

      // UI behaviour flags
      this._confirmImageUpload =
        this.$el.dataset.confirmImageUpload === "true";

      // Push notifications
      this._publicUrl = this.$el.dataset.publicUrl || "";
      if (this.notificationsSupported) {
        this._initPushState();
      }

      // Poll session list to detect deaths
      const refreshMs =
        parseInt(this.$el.dataset.sessionRefreshMs) || 3000;
      setInterval(() => this.refreshSessions(), refreshMs);

      // Restore active session from URL
      const params = new URLSearchParams(
        window.location.search
      );
      const restored = params.get("session");
      if (
        restored &&
        initialSessions.some(
          (s) => s.session_id === restored
        )
      ) {
        this._restoreSession(restored);
      }

      // Reload page when returning after 10 s away
      let hiddenAt = null;
      document.addEventListener(
        "visibilitychange",
        () => {
          if (document.visibilityState === "hidden") {
            hiddenAt = Date.now();
          } else if (
            hiddenAt &&
            Date.now() - hiddenAt > 10_000
          ) {
            location.reload();
          }
        }
      );
    },

    async refreshSessions() {
      const resp = await fetch("/api/v1/sessions");
      const sessions = await resp.json();
      this.sessions = sessions;
    },

    async createSession() {
      const dir = this.newWorkingDir.trim();
      if (!dir) return;
      const title = this.newTitle.trim();
      const resp = await fetch("/api/v1/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          working_dir: dir,
          title: title || null,
          agent_type: this.newAgentType,
        }),
      });
      if (resp.ok) {
        const session = await resp.json();
        this.sessions.push(session);
        this.switchSession(session.session_id);
        this.newWorkingDir = "";
        this.newTitle = "";
        this.newAgentType = "claude";
        this.refreshSessions();
        this.refreshRecentDirs();
      } else {
        const err = await resp.json();
        alert(err.detail || "Failed to create session");
      }
    },

    switchSession(sessionId) {
      const url = new URL(window.location);
      url.searchParams.set("session", sessionId);
      window.location.href = url.toString();
    },

    // Client-side restore used on initial page load
    // (URL already has ?session=...).
    _restoreSession(sessionId) {
      this.activeSession = null;
      this.$nextTick(() => {
        this.activeSession = sessionId;
        this.refreshSlashCommands();
        this.$nextTick(async () => {
          await this.loadHistory(sessionId, null);
          this._setupHistoryObserver();
          // Scroll to bottom after initial load
          this._pinned = true;
          const t = this.$refs.terminalScroll;
          if (t) t.scrollTop = t.scrollHeight;
        });
      });
    },

    async killSession(sessionId) {
      const ok = window.confirm(
        "Close this session? The agent process will be stopped."
      );
      if (!ok) return;
      await fetch(`/api/v1/sessions/${sessionId}`, {
        method: "DELETE",
      });
      // Mark dead locally instead of removing
      const s = this.sessions.find(
        (s) => s.session_id === sessionId
      );
      if (s) {
        s.is_alive = false;
        s.ended_at = Date.now() / 1000;
      }
      this.refreshSessions();
    },

    async removeDeadSession(sessionId) {
      if (!window.confirm("Remove this session from history?"))
        return;
      await fetch(`/api/v1/sessions/${sessionId}`, {
        method: "DELETE",
      });
      this.sessions = this.sessions.filter(
        (s) => s.session_id !== sessionId
      );
      if (this.activeSession === sessionId) {
        this.activeSession = null;
        const url = new URL(window.location);
        url.searchParams.delete("session");
        history.replaceState(null, "", url);
      }
    },

    async sendMessage() {
      const text = this.inputText.trim();
      if (!text || !this.activeSession) return;
      // Route freeform input to selectOption when in selection mode
      if (this.buttonLayout === "selection") {
        const freeItem = this.selectionItems.find(
          (i) => i.is_freeform
        );
        if (freeItem) {
          this.selectOption(freeItem.number, true);
          return;
        }
      }
      const ok = await this.sendToSession(text);
      if (ok) {
        this._pinned = true;
        this.inputText = "";
        const el = this.$refs.messageInput;
        el.style.height = "auto";
        el.focus();
      }
    },

    sendShortcut(name) {
      if (!this.activeSession) return;
      this.sendToSession(name);
    },

    async sendToSession(text) {
      try {
        const resp = await fetch(
          `/api/v1/sessions/${this.activeSession}/input`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text }),
          }
        );
        if (!resp.ok) return false;
        this._triggerPoll();
        return true;
      } catch {
        return false;
      }
    },

    async selectOption(itemNumber, isFreeform) {
      if (!this.activeSession) return;
      const body = { item_number: itemNumber };
      if (isFreeform && this.inputText.trim()) {
        body.freeform_text = this.inputText.trim();
      }
      await fetch(
        `/api/v1/sessions/${this.activeSession}/select`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      this.inputText = "";
      const el = this.$refs.messageInput;
      if (el) el.style.height = "auto";
      this._triggerPoll();
    },

    async refreshRecentDirs() {
      const resp = await fetch(
        "/api/v1/sessions/recent-dirs"
      );
      if (!resp.ok) return;
      this.recentDirs = await resp.json();
    },

    async refreshSlashCommands() {
      const sid = this.activeSession;
      const url = sid
        ? `/api/v1/sessions/slash-commands?session_id=${sid}`
        : "/api/v1/sessions/slash-commands";
      const resp = await fetch(url);
      if (!resp.ok) return;
      this.slashCommands = await resp.json();
    },

    async sendSlashCommand(cmd) {
      if (!this.activeSession) return;
      document.activeElement.blur();
      if (
        cmd.confirm &&
        !window.confirm(`Send ${cmd.text}?`)
      )
        return;
      await this.sendToSession(cmd.text);
      if (cmd.nav) this._slashNav = true;
    },

    insertSnippet(text) {
      const el = this.$refs.messageInput;
      if (!el) return;
      const start = el.selectionStart || 0;
      const before = this.inputText.slice(0, start);
      const after = this.inputText.slice(start);
      this.inputText = before + text + after;
      this.$nextTick(() => {
        const pos = start + text.length;
        el.selectionStart = pos;
        el.selectionEnd = pos;
        el.style.height = "auto";
        el.style.height = el.scrollHeight + "px";
        el.focus();
      });
    },

    attachPointerDown() {
      this._attachLongPressed = false;
      this._attachLongPressTimer = setTimeout(() => {
        this._attachLongPressed = true;
        this._attachPopoverOpen = true;
      }, 400);
    },

    attachPointerUp() {
      clearTimeout(this._attachLongPressTimer);
      if (this._attachLongPressed) {
        this._attachLongPressed = false;
        return;
      }
      this._attachPopoverOpen = !this._attachPopoverOpen;
    },

    debugSession() {
      if (!this.activeSession) return;
      this.debugDescription = "";
      this.showDebugModal = true;
      this.$nextTick(() => this.$refs.debugInput?.focus());
    },

    async submitDebug() {
      const description = this.debugDescription.trim();
      if (!description || !this.activeSession) return;
      this.showDebugModal = false;
      const resp = await fetch(
        `/api/v1/sessions/${this.activeSession}/debug`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ description }),
        }
      );
      if (resp.ok) {
        const session = await resp.json();
        this.sessions.push(session);
        this.switchSession(session.session_id);
        this.refreshSessions();
      } else {
        const err = await resp.json();
        alert(err.detail || "Failed to create debug session");
      }
    },

    // --- History scrollback ---

    async loadHistory(sessionId, before) {
      if (this.historyLoading || this.historyExhausted) return;
      this.historyLoading = true;

      const params = new URLSearchParams({
        mode: "history",
        limit: "50",
      });
      if (before) params.set("before", String(before));

      try {
        const resp = await fetch(
          `/api/v1/sessions/${sessionId}/output?${params}`
        );
        if (!resp.ok) return;
        const data = await resp.json();

        if (!data.chunks || data.chunks.length === 0) {
          // Only mark exhausted on pagination (before != null).
          // Empty initial load just means no history yet —
          // the observer should retry as chunks get captured.
          if (before) this.historyExhausted = true;
          return;
        }

        // Preserve scroll position when prepending
        const scrollEl = this.$refs.terminalScroll;
        const prevHeight = scrollEl ? scrollEl.scrollHeight : 0;

        this.historyChunks = [
          ...data.chunks,
          ...this.historyChunks,
        ];
        this.earliestTs = data.earliest_ts;

        // Adjust scroll so content doesn't jump.
        // await ensures adjustment completes before
        // loadHistory returns (callers can rely on
        // scrollTop being correct).
        if (before && scrollEl) {
          await this.$nextTick();
          const diff =
            scrollEl.scrollHeight - prevHeight;
          scrollEl.scrollTop += diff;
        }
      } finally {
        this.historyLoading = false;
      }
    },

    _setupHistoryObserver() {
      if (this._historyObserver) {
        this._historyObserver.disconnect();
      }
      this.$nextTick(() => {
        const sentinel = document.getElementById(
          "history-sentinel"
        );
        const root = this.$refs.terminalScroll;
        if (!sentinel || !root) return;

        this._historyObserver = new IntersectionObserver(
          (entries) => {
            if (
              entries[0].isIntersecting &&
              !this.historyExhausted &&
              !this.historyLoading &&
              this.activeSession
            ) {
              this.loadHistory(
                this.activeSession,
                this.earliestTs
              );
            }
          },
          { root, rootMargin: "200px 0px 0px 0px" }
        );
        this._historyObserver.observe(sentinel);
      });
    },

    _updateScrollTimestamp(scrollEl) {
      // Find the topmost visible history chunk
      const chunks = scrollEl.querySelectorAll(
        ".history-chunk[data-ts]"
      );
      if (!chunks.length) {
        this.scrollTimestamp = "";
        return;
      }
      const top = scrollEl.getBoundingClientRect().top;
      let ts = null;
      for (const el of chunks) {
        const rect = el.getBoundingClientRect();
        if (rect.bottom > top) {
          ts = parseFloat(el.dataset.ts);
          break;
        }
      }
      if (ts) {
        this.scrollTimestamp = this.formatChunkTs(ts);
        clearTimeout(this._scrollTsTimer);
        this._scrollTsTimer = setTimeout(() => {
          this.scrollTimestamp = "";
        }, 1500);
      } else {
        this.scrollTimestamp = "";
      }
    },

    // Returns [{key, y}, ...] sorted by y.
    // key = 60-char text snippet (stable anchor).
    _findPrompts(c) {
      const cTop = c.getBoundingClientRect().top;
      const walker = document.createTreeWalker(
        c,
        NodeFilter.SHOW_TEXT
      );
      // First-wins: keeps topmost occurrence so
      // history prompts aren't overwritten by
      // duplicates in live content.
      const seen = new Map();
      let node;
      while ((node = walker.nextNode())) {
        const text = node.textContent;
        // ❯ = Claude Code, › (U+203A) = Codex
        // \s not literal space — tmux renders
        // NBSP (U+00A0) after the prompt char.
        const re = /(^|\n)\s*[❯›]\s/g;
        let m;
        while ((m = re.exec(text))) {
          const idx =
            m.index + m[0].length - 2;
          const key = text
            .substring(idx, idx + 60)
            .trim();
          const range = document.createRange();
          range.setStart(node, idx);
          range.setEnd(node, idx + 1);
          const r = range.getBoundingClientRect();
          const y = r.top - cTop + c.scrollTop;
          if (!seen.has(key))
            seen.set(key, { key, y });
          range.detach();
        }
      }
      return [...seen.values()].sort(
        (a, b) => a.y - b.y
      );
    },

    async jumpToPrevPrompt() {
      const c = this.$refs.terminalScroll;
      if (!c) return;
      const viewTop = c.scrollTop;
      const found = this._findPrompts(c);
      const above = found.filter(
        (p) => p.y < viewTop - 10
      );

      if (above.length) {
        // Normal: jump to nearest prompt above
        const t = above[above.length - 1].y;
        this._pinned = false;
        this._jumpGuard = true;
        c.scrollTop = t - 20;
        this._updateScrollTimestamp(c);
        return;
      }

      // No prompts above — load history batches
      // until new prompts appear or exhausted.
      if (
        this.historyExhausted ||
        !this.activeSession
      )
        return;

      const oldKeys = new Set(
        found.map((p) => p.key)
      );
      let attempts = 0;
      while (
        attempts < 5 &&
        !this.historyExhausted
      ) {
        attempts++;
        await this.loadHistory(
          this.activeSession,
          this.earliestTs
        );
        const fresh = this._findPrompts(c);
        const novel = fresh.filter(
          (p) => !oldKeys.has(p.key)
        );
        if (novel.length) {
          // Jump to the most recent new prompt
          // (highest y = closest to user).
          const t =
            novel[novel.length - 1].y;
          this._pinned = false;
          this._jumpGuard = true;
          c.scrollTop = t - 20;
          this._updateScrollTimestamp(c);
          return;
        }
      }
    },

    jumpToNextPrompt() {
      const c = this.$refs.terminalScroll;
      if (!c) return;
      const viewTop = c.scrollTop;
      const found = this._findPrompts(c);
      const below = found.filter(
        (p) => p.y > viewTop + c.clientHeight + 10
      );
      if (below.length) {
        const t = below[0].y;
        this._pinned = false;
        this._jumpGuard = true;
        c.scrollTop = t - 20;
        this._updateScrollTimestamp(c);
      }
    },

    _triggerPoll() {
      setTimeout(() => {
        const el = document.getElementById(
          "terminal-container"
        );
        if (el) htmx.trigger(el, "poll");
      }, 100);
    },

    // --- Push notifications ---

    async _initPushState() {
      try {
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        this._pushSubscription = sub;
        if (sub) {
          const resp = await fetch(
            `/api/v1/notifications/subscriptions?endpoint=${encodeURIComponent(sub.endpoint)}`
          );
          if (resp.ok) {
            const ids = await resp.json();
            this._notifiedSessions = new Set(ids);
          }
        }
      } catch {
        // Push not available
      }
    },

    async toggleNotification() {
      if (!this.activeSession) return;
      const sid = this.activeSession;

      try {
        // Ensure we have a push subscription
        if (!this._pushSubscription) {
          const perm = await Notification.requestPermission();
          if (perm !== "granted") return;

          const resp = await fetch("/api/v1/notifications/vapid-key");
          const { public_key } = await resp.json();
          const reg = await navigator.serviceWorker.ready;
          const sub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: public_key,
          });
          this._pushSubscription = sub;
        }

        const sub = this._pushSubscription;
        const key = sub.getKey("p256dh");
        const auth = sub.getKey("auth");
        const p256dh = btoa(String.fromCharCode(...new Uint8Array(key)));
        const authStr = btoa(String.fromCharCode(...new Uint8Array(auth)));

        if (this._notifiedSessions.has(sid)) {
          // Unsubscribe
          await fetch("/api/v1/notifications/unsubscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              endpoint: sub.endpoint,
              session_id: sid,
            }),
          });
          this._notifiedSessions.delete(sid);
          // Force Alpine reactivity
          this._notifiedSessions = new Set(this._notifiedSessions);
        } else {
          // Subscribe
          await fetch("/api/v1/notifications/subscribe", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              endpoint: sub.endpoint,
              p256dh: p256dh,
              auth: authStr,
              session_id: sid,
            }),
          });
          this._notifiedSessions.add(sid);
          this._notifiedSessions = new Set(this._notifiedSessions);
        }
      } catch (err) {
        console.error("Push notification toggle failed:", err);
      }
    },

    async pasteImage(event) {
      const file = event.target.files?.[0];
      if (!file || !this.activeSession) return;
      if (
        this._confirmImageUpload &&
        !window.confirm("Send image to agent?")
      ) {
        event.target.value = "";
        return;
      }
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch(
        `/api/v1/sessions/${this.activeSession}/image`,
        { method: "POST", body: form }
      );
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        alert(err.detail || "Image paste failed");
      }
      event.target.value = "";
      this._triggerPoll();
    },
  }));
});
