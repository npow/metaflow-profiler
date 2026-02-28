"""Unit tests for concrete backend implementations."""

from __future__ import annotations

import time

import pytest

from metaflow_extensions.profiler.plugins.profiler import ProfileData
from metaflow_extensions.profiler.plugins.profilers.cprofile_backend import CProfileBackend


class TestCProfileBackend:
    def test_is_always_available(self):
        assert CProfileBackend.is_available() is True

    def test_start_stop_returns_profile_data(self):
        backend = CProfileBackend(timeline_interval=0.1)
        backend.start()
        # Minimal workload so there's something to profile
        sum(range(50_000))
        data = backend.stop()

        assert isinstance(data, ProfileData)
        assert data.backend == "cprofile"
        assert data.duration >= 0
        assert data.sample_count >= 0

    def test_extended_fields_have_defaults(self):
        backend = CProfileBackend(timeline_interval=0.1)
        backend.start()
        _ = sum(range(10_000))
        data = backend.stop()

        # New extended fields must exist and have valid default values
        assert hasattr(data, "memory_tree")
        assert data.memory_tree is None or isinstance(data.memory_tree, dict)
        assert data.peak_disk_read_mb_s >= 0
        assert data.peak_disk_write_mb_s >= 0
        assert data.peak_net_recv_mb_s >= 0
        assert data.peak_net_sent_mb_s >= 0
        assert data.peak_gpu_pct >= 0
        assert data.peak_gpu_mem_mb >= 0

    def test_stop_before_start_raises(self):
        backend = CProfileBackend()
        with pytest.raises(RuntimeError, match="before start"):
            backend.stop()

    def test_call_tree_structure(self):
        backend = CProfileBackend(timeline_interval=0.2)
        backend.start()
        # Nested calls to encourage a tree
        def inner(): return sum(range(1000))
        def outer(): return inner() + inner()
        outer()
        data = backend.stop()
        if data.call_tree is not None:
            assert "name"  in data.call_tree
            assert "value" in data.call_tree

    def test_peak_cpu_non_negative(self):
        backend = CProfileBackend(timeline_interval=0.1)
        backend.start()
        _ = [i**2 for i in range(10_000)]
        data = backend.stop()
        assert data.peak_cpu_pct >= 0

    def test_peak_rss_positive(self):
        backend = CProfileBackend(timeline_interval=0.1)
        backend.start()
        _ = list(range(100_000))
        data = backend.stop()
        # RSS may be 0 if psutil is not installed
        assert data.peak_rss_mb >= 0


@pytest.mark.skipif(
    not __import__("importlib").util.find_spec("pyinstrument"),
    reason="pyinstrument not installed",
)
class TestPyinstrumentBackend:
    def test_is_available(self):
        from metaflow_extensions.profiler.plugins.profilers.pyinstrument import PyinstrumentBackend
        assert PyinstrumentBackend.is_available() is True

    def test_start_stop_returns_profile_data(self):
        from metaflow_extensions.profiler.plugins.profilers.pyinstrument import PyinstrumentBackend
        backend = PyinstrumentBackend(sample_interval=0.001, timeline_interval=0.1)
        backend.start()
        time.sleep(0.05)  # let the profiler collect a few samples
        _ = sum(range(100_000))
        data = backend.stop()

        assert isinstance(data, ProfileData)
        assert data.backend == "pyinstrument"
        assert data.duration > 0

    def test_call_tree_has_children(self):
        from metaflow_extensions.profiler.plugins.profilers.pyinstrument import PyinstrumentBackend
        backend = PyinstrumentBackend(sample_interval=0.001, timeline_interval=0.1)
        backend.start()
        time.sleep(0.1)
        _ = [x**2 for x in range(100_000)]
        data = backend.stop()

        if data.call_tree is not None:
            assert data.call_tree["name"] == "root"

    def test_extended_fields_have_defaults(self):
        from metaflow_extensions.profiler.plugins.profilers.pyinstrument import PyinstrumentBackend
        backend = PyinstrumentBackend(sample_interval=0.001, timeline_interval=0.1)
        backend.start()
        time.sleep(0.05)
        data = backend.stop()

        assert hasattr(data, "memory_tree")
        assert data.memory_tree is None or isinstance(data.memory_tree, dict)
        assert data.peak_disk_read_mb_s >= 0
        assert data.peak_net_recv_mb_s >= 0
        assert data.peak_gpu_pct >= 0
