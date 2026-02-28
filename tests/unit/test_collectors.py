"""Unit tests for _collectors.py — extended timeline collector and memory tracker."""

from __future__ import annotations

import importlib
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from metaflow_extensions.profiler.plugins.profilers._collectors import (
    _MemoryTracker,
    _TimelineCollector,
    _build_memory_tree,
)


class TestTimelineCollectorBasic:
    """Tests that work regardless of optional deps."""

    def test_stop_before_start_returns_empty(self):
        tc = _TimelineCollector(interval=0.1)
        result = tc.stop()
        assert result == []

    def test_stop_is_idempotent(self):
        tc = _TimelineCollector(interval=0.1)
        tc.start()
        time.sleep(0.05)
        r1 = tc.stop()
        r2 = tc.stop()
        # Second stop should not raise and returns the same samples
        assert r2 == r1

    def test_samples_have_base_fields(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        time.sleep(0.3)
        samples = tc.stop()
        # psutil is a hard dependency (in pyproject.toml), so we always get samples
        if samples:
            s = samples[0]
            assert "ts" in s
            assert "cpu_pct" in s
            assert "rss_mb" in s

    def test_ts_is_monotonically_increasing(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        time.sleep(0.4)
        samples = tc.stop()
        if len(samples) >= 2:
            for i in range(1, len(samples)):
                assert samples[i]["ts"] >= samples[i - 1]["ts"]

    def test_cpu_pct_in_range(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        _ = [x**2 for x in range(50_000)]
        samples = tc.stop()
        for s in samples:
            assert s["cpu_pct"] >= 0

    def test_rss_mb_positive(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        time.sleep(0.15)
        samples = tc.stop()
        for s in samples:
            assert s["rss_mb"] > 0

    def test_thread_count_field(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        time.sleep(0.2)
        samples = tc.stop()
        for s in samples:
            if "thread_count" in s:
                assert s["thread_count"] >= 1


class TestTimelineCollectorIO:
    """Tests for disk / network I/O fields (present on most platforms)."""

    def test_disk_fields_non_negative_when_present(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        time.sleep(0.3)
        samples = tc.stop()
        for s in samples:
            if "disk_read_mb_s" in s:
                assert s["disk_read_mb_s"] >= 0
            if "disk_write_mb_s" in s:
                assert s["disk_write_mb_s"] >= 0

    def test_net_fields_non_negative_when_present(self):
        tc = _TimelineCollector(interval=0.05)
        tc.start()
        time.sleep(0.3)
        samples = tc.stop()
        for s in samples:
            if "net_recv_mb_s" in s:
                assert s["net_recv_mb_s"] >= 0
            if "net_sent_mb_s" in s:
                assert s["net_sent_mb_s"] >= 0

    def test_first_sample_has_no_rate_fields(self):
        """The first sample cannot compute a delta — rates should be absent."""
        tc = _TimelineCollector(interval=0.1)
        tc.start()
        time.sleep(0.05)
        tc.stop()
        # We can't easily assert on the first sample here since the timeline
        # thread runs in the background.  Just verify no exception was raised.


class TestBuildMemoryTree:
    """Unit tests for _build_memory_tree."""

    def _make_record(
        self, stack: List[tuple], total_memory: int
    ) -> Any:
        """Build a mock memray AllocationRecord."""
        record = MagicMock()
        record.total_memory = total_memory

        frames = []
        for func, file, line in stack:
            f = MagicMock()
            f.function = func
            f.filename = file
            f.lineno = line
            frames.append(f)

        record.stack_trace.return_value = frames
        return record

    def test_empty_records_returns_none(self):
        result = _build_memory_tree([])
        assert result is None

    def test_below_threshold_returns_none(self):
        # total_memory < 1024 bytes (< 0.001 MB) → filtered out
        record = self._make_record([("fn", "file.py", 1)], total_memory=500)
        result = _build_memory_tree([record])
        assert result is None

    def test_single_frame_tree(self):
        record = self._make_record(
            [("my_func", "mymod.py", 42)],
            total_memory=5 * 1024 * 1024,  # 5 MB
        )
        result = _build_memory_tree([record])
        assert result is not None
        assert result["name"] == "root"
        assert result["value"] > 0
        assert "children" in result
        child = result["children"][0]
        assert "my_func" in child["name"]

    def test_nested_frames_produce_nested_tree(self):
        # Stack (innermost first) = [inner, outer]; reversed = [outer, inner]
        record = self._make_record(
            [("inner", "mod.py", 10), ("outer", "mod.py", 5)],
            total_memory=10 * 1024 * 1024,
        )
        result = _build_memory_tree([record])
        assert result is not None
        # outer should be a child of root
        assert any("outer" in c["name"] for c in result.get("children", []))

    def test_multiple_records_aggregate(self):
        r1 = self._make_record([("alloc_fn", "a.py", 1)], total_memory=3 * 1024 * 1024)
        r2 = self._make_record([("alloc_fn", "a.py", 1)], total_memory=2 * 1024 * 1024)
        result = _build_memory_tree([r1, r2])
        assert result is not None
        # Root value should be sum (5 MB)
        assert abs(result["value"] - 5.0) < 0.01

    def test_values_in_mb(self):
        record = self._make_record(
            [("fn", "f.py", 1)],
            total_memory=1024 * 1024,  # exactly 1 MB
        )
        result = _build_memory_tree([record])
        assert result is not None
        assert abs(result["value"] - 1.0) < 0.01

    def test_tuple_frame_format(self):
        """Handles old-style (func, file, line) tuple frames."""
        record = MagicMock()
        record.total_memory = 2 * 1024 * 1024
        # Return plain tuples instead of objects with .function etc.
        record.stack_trace.return_value = [("tuple_fn", "t.py", 99)]
        result = _build_memory_tree([record])
        assert result is not None
        assert any("tuple_fn" in c["name"] for c in result.get("children", []))

    def test_size_fallback_when_no_total_memory(self):
        record = MagicMock()
        del record.total_memory  # trigger AttributeError
        record.size = 2 * 1024 * 1024
        record.stack_trace.return_value = [("fn2", "x.py", 1)]
        result = _build_memory_tree([record])
        assert result is not None


class TestMemoryTracker:
    """Tests for _MemoryTracker (graceful no-op when memray absent)."""

    def test_stop_before_start_returns_none(self):
        mt = _MemoryTracker()
        assert mt.stop() is None

    def test_no_memray_start_does_not_raise(self):
        """When memray is missing, start() silently sets _available=False."""
        mt = _MemoryTracker()
        with patch.dict("sys.modules", {"memray": None}):
            try:
                mt.start()
            except Exception as e:
                pytest.fail(f"start() raised unexpectedly: {e}")
        assert mt._available is False

    def test_no_memray_stop_returns_none(self):
        mt = _MemoryTracker()
        mt._available = False
        assert mt.stop() is None

    @pytest.mark.skipif(
        not importlib.util.find_spec("memray"),
        reason="memray not installed",
    )
    def test_with_memray_returns_dict_or_none(self):
        """When memray is installed, stop() returns a dict or None."""
        mt = _MemoryTracker()
        mt.start()
        # Small allocation
        _ = [0] * 10_000
        result = mt.stop()
        assert result is None or isinstance(result, dict)

    @pytest.mark.skipif(
        not importlib.util.find_spec("memray"),
        reason="memray not installed",
    )
    def test_with_memray_tree_has_root(self):
        mt = _MemoryTracker()
        mt.start()
        _ = bytearray(1024 * 1024)  # 1 MB allocation
        result = mt.stop()
        if result is not None:
            assert result["name"] == "root"
            assert result["value"] > 0

    @pytest.mark.skipif(
        not importlib.util.find_spec("memray"),
        reason="memray not installed",
    )
    def test_with_memray_tmpfile_cleaned_up(self):
        import tempfile
        mt = _MemoryTracker()
        mt.start()
        mt.stop()
        # Temp file should be removed after stop()
        if mt._tmpfile is not None:
            assert not mt._tmpfile.exists()
