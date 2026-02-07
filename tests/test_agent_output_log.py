"""Tests for AgentOutputLog (SQLite + FTS5)."""

import time
from collections.abc import Generator
from pathlib import Path

import pytest

from agentdeck.sessions.agent_output_log import AgentOutputLog


@pytest.fixture
def log(tmp_path: Path) -> Generator[AgentOutputLog]:
    db = AgentOutputLog(tmp_path / "test.db")
    yield db
    db.close()


class TestAppend:
    def test_append_stores_lines(self, log: AgentOutputLog):
        log.append("s1", ["hello", "world"])
        page = log.read("s1")
        assert len(page.chunks) == 1
        assert page.chunks[0].content == "hello\nworld"
        assert page.chunks[0].session_id == "s1"

    def test_append_empty_is_noop(self, log: AgentOutputLog):
        log.append("s1", [])
        page = log.read("s1")
        assert len(page.chunks) == 0

    def test_append_multiple_chunks(self, log: AgentOutputLog):
        log.append("s1", ["line1"])
        log.append("s1", ["line2"])
        log.append("s1", ["line3"])
        page = log.read("s1")
        assert len(page.chunks) == 3
        # Chronological order
        assert page.chunks[0].content == "line1"
        assert page.chunks[2].content == "line3"


class TestRead:
    def test_read_empty_session(self, log: AgentOutputLog):
        page = log.read("nonexistent")
        assert page.chunks == []
        assert page.earliest_ts is None

    def test_read_returns_chronological(self, log: AgentOutputLog):
        log.append("s1", ["a"])
        log.append("s1", ["b"])
        log.append("s1", ["c"])
        page = log.read("s1")
        contents = [c.content for c in page.chunks]
        assert contents == ["a", "b", "c"]

    def test_read_with_before(self, log: AgentOutputLog):
        log.append("s1", ["old"])
        old_ts = log.latest_ts("s1")
        assert old_ts is not None
        # Small delay to ensure different timestamp
        time.sleep(0.01)
        log.append("s1", ["new"])
        new_ts = log.latest_ts("s1")
        assert new_ts is not None

        # Only get chunks before the new one
        page = log.read("s1", before=new_ts)
        assert len(page.chunks) == 1
        assert page.chunks[0].content == "old"

    def test_read_with_limit(self, log: AgentOutputLog):
        for i in range(10):
            log.append("s1", [f"line{i}"])
        page = log.read("s1", limit=3)
        assert len(page.chunks) == 3
        # Should be the 3 most recent, in chrono order
        contents = [c.content for c in page.chunks]
        assert contents == ["line7", "line8", "line9"]

    def test_read_isolates_sessions(self, log: AgentOutputLog):
        log.append("s1", ["from s1"])
        log.append("s2", ["from s2"])
        page = log.read("s1")
        assert len(page.chunks) == 1
        assert page.chunks[0].content == "from s1"

    def test_earliest_ts_set(self, log: AgentOutputLog):
        log.append("s1", ["a"])
        time.sleep(0.01)
        log.append("s1", ["b"])
        page = log.read("s1")
        assert page.earliest_ts is not None
        assert page.earliest_ts == page.chunks[0].ts
        assert page.earliest_ts < page.chunks[1].ts


class TestSearch:
    def test_search_finds_match(self, log: AgentOutputLog):
        log.append("s1", ["error: file not found"])
        log.append("s1", ["success: all good"])
        results = log.search("error")
        assert len(results) == 1
        assert "error" in results[0].snippet.lower()

    def test_search_cross_session(self, log: AgentOutputLog):
        log.append("s1", ["auth failed"])
        log.append("s2", ["auth succeeded"])
        results = log.search("auth")
        assert len(results) == 2
        sessions = {r.session_id for r in results}
        assert sessions == {"s1", "s2"}

    def test_search_scoped_to_session(self, log: AgentOutputLog):
        log.append("s1", ["auth failed"])
        log.append("s2", ["auth succeeded"])
        results = log.search("auth", session_id="s1")
        assert len(results) == 1
        assert results[0].session_id == "s1"

    def test_search_no_results(self, log: AgentOutputLog):
        log.append("s1", ["hello world"])
        results = log.search("nonexistent")
        assert results == []

    def test_search_snippet_has_markers(self, log: AgentOutputLog):
        log.append("s1", ["the quick brown fox jumps"])
        results = log.search("fox")
        assert len(results) == 1
        assert "<b>" in results[0].snippet
        assert "</b>" in results[0].snippet


class TestLatestTs:
    def test_latest_ts_empty(self, log: AgentOutputLog):
        assert log.latest_ts("nonexistent") is None

    def test_latest_ts_returns_most_recent(self, log: AgentOutputLog):
        log.append("s1", ["old"])
        ts1 = log.latest_ts("s1")
        time.sleep(0.01)
        log.append("s1", ["new"])
        ts2 = log.latest_ts("s1")
        assert ts1 is not None
        assert ts2 is not None
        assert ts2 > ts1


class TestSessionIds:
    def test_session_ids_empty(self, log: AgentOutputLog):
        assert log.session_ids() == []

    def test_session_ids_returns_all(self, log: AgentOutputLog):
        log.append("s1", ["a"])
        log.append("s2", ["b"])
        log.append("s1", ["c"])
        ids = set(log.session_ids())
        assert ids == {"s1", "s2"}


class TestSoftDelete:
    def test_soft_delete_excludes_from_session_ids(self, log: AgentOutputLog):
        log.append("s1", ["a"])
        log.append("s2", ["b"])
        log.soft_delete("s1")
        assert log.session_ids() == ["s2"]

    def test_soft_deleted_data_excluded_from_read(self, log: AgentOutputLog):
        """Archived chunks are excluded from read()."""
        log.append("s1", ["hello"])
        log.soft_delete("s1")
        page = log.read("s1")
        assert len(page.chunks) == 0

    def test_soft_delete_idempotent(self, log: AgentOutputLog):
        log.append("s1", ["a"])
        log.soft_delete("s1")
        log.soft_delete("s1")
        assert "s1" not in log.session_ids()
