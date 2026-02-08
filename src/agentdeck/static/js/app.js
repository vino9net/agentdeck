/* Alpine.js component for agentdeck */
document.addEventListener("alpine:init", () => {
  Alpine.data("codeServer", () => ({
    activeSession: null,
    inputText: "",
    connected: false,
    listening: false,
    sessions: [],
    recentDirs: [],
    newTitle: "",
    newWorkingDir: "",
    newAgentType: "claude",
    recognition: null,
    uiState: "working",
    selectionItems: [],
    selectedIndex: 0,
    selectionQuestion: "",
    freeformText: "",
    slashCommands: [],
    showDebugModal: false,
    debugDescription: "",

    // History scrollback state
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

        target.addEventListener("scroll", () => {
          const gap =
            target.scrollHeight -
            target.scrollTop -
            target.clientHeight;
          this._pinned = gap < 50;
          this._updateScrollTimestamp(target);
        });

        target.addEventListener("wheel", (e) => {
          if (e.deltaY < 0) this._pinned = false;
        });

        const observer = new MutationObserver(() => {
          if (this._pinned && !this.historyLoading) {
            target.scrollTop = target.scrollHeight;
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
          if (data.state !== "selection") {
            this.freeformText = "";
          }
        } catch {
          // Ignore parse errors
        }
      });

      const initialSessions = this.$el.dataset.sessions
        ? JSON.parse(this.$el.dataset.sessions)
        : [];
      this.sessions = initialSessions;
      this.refreshSessions();
      this.refreshRecentDirs();
      this.refreshSlashCommands();

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
        this.switchSession(restored);
      }
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
      // Clear history state
      this.historyChunks = [];
      this.earliestTs = null;
      this.historyExhausted = false;
      this.historyLoading = false;
      if (this._historyObserver) {
        this._historyObserver.disconnect();
        this._historyObserver = null;
      }

      // Null first to force x-if to destroy and recreate
      this.activeSession = null;
      this.$nextTick(() => {
        this.activeSession = sessionId;
        this.refreshSlashCommands();
        this.$nextTick(() => {
          this.loadHistory(sessionId, null);
          this._setupHistoryObserver();
        });
      });
      // Persist to URL so refresh restores the session
      const url = new URL(window.location);
      url.searchParams.set("session", sessionId);
      history.replaceState(null, "", url);
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

    sendMessage() {
      const text = this.inputText.trim();
      if (!text || !this.activeSession) return;
      this.sendToSession(text);
      this.inputText = "";
      const el = this.$refs.messageInput;
      el.style.height = "auto";
      el.focus();
    },

    sendShortcut(name) {
      if (!this.activeSession) return;
      this.sendToSession(name);
    },

    async sendToSession(text) {
      await fetch(
        `/api/v1/sessions/${this.activeSession}/input`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        }
      );
      this._triggerPoll();
    },

    async selectOption(itemNumber, isFreeform) {
      if (!this.activeSession) return;
      const body = { item_number: itemNumber };
      if (isFreeform && this.freeformText.trim()) {
        body.freeform_text = this.freeformText.trim();
      }
      await fetch(
        `/api/v1/sessions/${this.activeSession}/select`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      this.freeformText = "";
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

        // Adjust scroll so content doesn't jump
        if (before && scrollEl) {
          this.$nextTick(() => {
            const diff = scrollEl.scrollHeight - prevHeight;
            scrollEl.scrollTop += diff;
          });
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
        // Auto-hide after 1.5s of no scrolling
        clearTimeout(this._scrollTsTimer);
        this._scrollTsTimer = setTimeout(() => {
          this.scrollTimestamp = "";
        }, 1500);
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

    toggleVoice() {
      if (
        !(
          "webkitSpeechRecognition" in window ||
          "SpeechRecognition" in window
        )
      ) {
        alert("Voice input not supported in this browser");
        return;
      }
      if (this.listening) {
        this.recognition.stop();
        this.listening = false;
        return;
      }
      const SR =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;
      this.recognition = new SR();
      this.recognition.continuous = false;
      this.recognition.interimResults = false;
      this.recognition.onresult = (event) => {
        const text = event.results[0][0].transcript;
        const el = this.$refs.messageInput;
        const start = el.selectionStart;
        const end = el.selectionEnd;
        this.inputText =
          this.inputText.slice(0, start) +
          text +
          this.inputText.slice(end);
        this.$nextTick(() => {
          const pos = start + text.length;
          el.setSelectionRange(pos, pos);
          el.focus();
        });
        this.listening = false;
      };
      this.recognition.onerror = (event) => {
        this.listening = false;
        if (event.error !== "aborted") {
          console.error(
            "Speech recognition error:",
            event.error
          );
        }
      };
      this.recognition.onend = () => {
        this.listening = false;
      };
      this.recognition.start();
      this.listening = true;
    },
  }));
});
