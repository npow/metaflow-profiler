"""Unit tests for the ProfileCard HTML renderer."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from metaflow_extensions.profiler.plugins.cards.profile_card.card import ProfileCard
from metaflow_extensions.profiler.plugins.cards.profile_card.card import _error_html
from metaflow_extensions.profiler.plugins.cards.profile_card.card import _fmt_duration
from metaflow_extensions.profiler.plugins.cards.profile_card.card import _fmt_mb
from metaflow_extensions.profiler.plugins.cards.profile_card.card import _render_card

_SAMPLE_DATA = {
    "backend": "cprofile",
    "duration": 3.14,
    "sample_count": 5000,
    "call_tree": {
        "name": "root",
        "value": 3140.0,
        "children": [
            {
                "name": "heavy_fn (utils.py:42)",
                "value": 2000.0,
                "file": "utils.py",
                "line": 42,
                "children": [
                    {"name": "inner (utils.py:10)", "value": 1000.0, "file": "utils.py", "line": 10},  # noqa: E501
                ],
            },
            {"name": "light_fn (utils.py:99)", "value": 1140.0, "file": "utils.py", "line": 99},
        ],
    },
    "memory_tree": {
        "name": "root",
        "value": 50.0,
        "children": [
            {"name": "alloc_fn (mem.py:5)", "value": 30.0},
            {"name": "other_fn (mem.py:20)", "value": 20.0},
        ],
    },
    "timeline": [
        {"ts": 0.0, "cpu_pct": 10.0, "rss_mb": 100.0,
         "disk_read_mb_s": 0.5, "disk_write_mb_s": 0.1,
         "net_recv_mb_s": 0.2, "net_sent_mb_s": 0.05, "thread_count": 4.0},
        {"ts": 0.5, "cpu_pct": 95.0, "rss_mb": 200.0,
         "disk_read_mb_s": 1.2, "disk_write_mb_s": 0.3,
         "net_recv_mb_s": 0.8, "net_sent_mb_s": 0.1, "thread_count": 4.0},
        {"ts": 1.0, "cpu_pct": 80.0, "rss_mb": 180.0,
         "disk_read_mb_s": 0.3, "disk_write_mb_s": 0.05,
         "net_recv_mb_s": 0.1, "net_sent_mb_s": 0.02, "thread_count": 4.0},
    ],
    "peak_cpu_pct": 95.0,
    "peak_rss_mb": 200.0,
    "avg_cpu_pct": 61.7,
    "avg_rss_mb": 160.0,
    "peak_disk_read_mb_s": 1.2,
    "peak_disk_write_mb_s": 0.3,
    "peak_net_recv_mb_s": 0.8,
    "peak_net_sent_mb_s": 0.1,
    "peak_gpu_pct": 0.0,
    "peak_gpu_mem_mb": 0.0,
}


class TestFormatters:
    @pytest.mark.parametrize("s,expected", [
        (0.0005, "0.500 ms"),
        (0.5, "500 ms"),
        (1.0, "1.00 s"),
        (90.0, "1m 30.0s"),
        (120.0, "2m 0.0s"),
    ])
    def test_fmt_duration(self, s, expected):
        assert _fmt_duration(s) == expected

    @pytest.mark.parametrize("mb,expected", [
        (512.0, "512.0 MB"),
        (1024.0, "1.00 GB"),
        (2048.5, "2.00 GB"),
    ])
    def test_fmt_mb(self, mb, expected):
        assert _fmt_mb(mb) == expected


class TestErrorHtml:
    def test_contains_title(self):
        html = _error_html("Something went wrong", detail="details here")
        assert "Something went wrong" in html
        assert "details here" in html

    def test_traceback_in_details(self):
        html = _error_html("Oops", traceback="line 1\nline 2")
        assert "line 1" in html
        assert "<details" in html

    def test_no_traceback_no_details_tag(self):
        html = _error_html("Oops")
        assert "<details" not in html


class TestRenderCard:
    def _make_task(self):
        task = MagicMock()
        task.id = "MyFlow/123/my_step/456"
        return task

    def test_returns_html_string(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert isinstance(html, str)
        assert html.startswith("<!DOCTYPE html>")

    def test_contains_backend_name(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "cprofile" in html

    def test_contains_duration(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "3.14 s" in html

    def test_failed_banner_shown(self):
        html = _render_card(_SAMPLE_DATA, step_failed=True, task=self._make_task())
        # When the step failed, a visible div with the failed-banner class is injected
        assert '<div class="failed-banner">' in html

    def test_failed_banner_not_shown_on_success(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        # The CSS defines .failed-banner but the div should not be rendered
        assert '<div class="failed-banner">' not in html

    def test_js_data_serialised(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "PROFILE_DATA" in html
        assert "heavy_fn" in html  # call tree name present in JSON

    def test_step_name_extracted(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "my_step" in html

    def test_peak_cpu_shown(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "95.0%" in html

    def test_peak_mem_shown(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "200.0 MB" in html

    def test_memory_flamegraph_section_present(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "mem-flame-section" in html
        assert "Memory Flamegraph" in html
        assert "mem-canvas" in html

    def test_memory_tree_in_js_data(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "alloc_fn" in html  # from memory_tree

    def test_io_section_in_html(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "io-section" in html
        assert "io-canvas" in html
        assert "I/O Timeline" in html

    def test_gpu_section_in_html(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "gpu-section" in html
        assert "gpu-canvas" in html

    def test_disk_stat_shown_when_nonzero(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "Peak Disk Read" in html
        assert "1.20 MB/s" in html

    def test_gpu_stat_not_shown_when_zero(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        # peak_gpu_pct = 0 in _SAMPLE_DATA, so the GPU stat card should be absent
        assert "Peak GPU" not in html

    def test_no_memory_tree_hides_section(self):
        data = dict(_SAMPLE_DATA)
        data["memory_tree"] = None
        html = _render_card(data, step_failed=False, task=self._make_task())
        # Section is in HTML but hidden (style="display:none")
        assert 'id="mem-flame-section" style="display:none"' in html

    def test_extended_io_data_in_timeline_json(self):
        html = _render_card(_SAMPLE_DATA, step_failed=False, task=self._make_task())
        assert "disk_read_mb_s" in html
        assert "net_recv_mb_s" in html


class TestProfileCard:
    def test_type_attribute(self):
        assert ProfileCard.type == "profile_card"

    def test_render_missing_artifact(self):
        task = MagicMock()
        task.data = MagicMock(spec=[])  # no attributes
        card = ProfileCard()
        html = card.render(task)
        assert "No profiling data found" in html

    def test_render_error_artifact(self):
        task = MagicMock()
        task.data.profile_card_data = {
            "error": {"type": "RuntimeError", "message": "backend crashed"}
        }
        card = ProfileCard()
        html = card.render(task)
        assert "Profiler error" in html
        assert "backend crashed" in html

    def test_render_good_artifact(self):
        task = MagicMock()
        task.data.profile_card_data = {
            "step_failed": False,
            "data": _SAMPLE_DATA,
        }
        task.id = "MyFlow/1/train/0"
        card = ProfileCard()
        html = card.render(task)
        assert "<!DOCTYPE html>" in html
        assert "cprofile" in html

    def test_custom_artifact_name(self):
        card = ProfileCard(options={"artifact_name": "my_profile"})
        task = MagicMock()
        task.data = MagicMock(spec=["my_profile"])
        task.data.my_profile = {
            "step_failed": False,
            "data": _SAMPLE_DATA,
        }
        task.id = "MyFlow/1/train/0"
        html = card.render(task)
        assert "<!DOCTYPE html>" in html
