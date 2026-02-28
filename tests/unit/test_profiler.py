"""Unit tests for the ProfileData dataclass and backend ABC."""

from __future__ import annotations

import dataclasses

import pytest

from metaflow_extensions.profiler.plugins.profiler import ProfileData
from metaflow_extensions.profiler.plugins.profiler import ProfilerBackend


class TestProfileData:
    def test_fields_present(self):
        fields = {f.name for f in dataclasses.fields(ProfileData)}
        required = {
            "backend", "duration", "sample_count",
            "call_tree", "timeline",
            "peak_cpu_pct", "peak_rss_mb",
            "avg_cpu_pct", "avg_rss_mb",
        }
        assert required <= fields

    def test_asdict_roundtrip(self):
        pd = ProfileData(
            backend="test",
            duration=1.5,
            sample_count=100,
            call_tree={"name": "root", "value": 1500.0},
            timeline=[{"ts": 0.0, "cpu_pct": 50.0, "rss_mb": 200.0}],
            peak_cpu_pct=80.0,
            peak_rss_mb=300.0,
            avg_cpu_pct=50.0,
            avg_rss_mb=250.0,
        )
        d = dataclasses.asdict(pd)
        assert d["backend"] == "test"
        assert d["duration"] == 1.5
        assert isinstance(d["timeline"], list)
        assert d["call_tree"]["value"] == 1500.0

    def test_call_tree_optional(self):
        pd = ProfileData(
            backend="cprofile",
            duration=0.1,
            sample_count=10,
            call_tree=None,
            timeline=[],
            peak_cpu_pct=0.0,
            peak_rss_mb=0.0,
            avg_cpu_pct=0.0,
            avg_rss_mb=0.0,
        )
        assert pd.call_tree is None


class TestProfilerBackend:
    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            ProfilerBackend()  # type: ignore[abstract]
