"""cProfile backend — deterministic profiling, always available.

Layer: Backend Implementation
May only import from: ..profiler (ABC), standard library, psutil

Uses Python's built-in ``cProfile`` module.  Because cProfile does not
produce a native call-tree suitable for flamegraph rendering, this backend
builds a best-effort tree by walking the ``callers`` mapping in pstats.
The resulting flamegraph may not be 100% accurate for recursive code, but
is a useful visual summary.  Falls back to ``call_tree=None`` if tree
construction fails, in which case the card shows a top-functions bar chart.
"""

from __future__ import annotations

import cProfile
import io
import pstats
import sys
import time
import threading
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from ..profiler import ProfileData
from ..profiler import ProfilerBackend
from . import register
from ._collectors import _MemoryTracker
from ._collectors import _TimelineCollector


# ── call-tree builder ─────────────────────────────────────────────────────────

_Key = Tuple[str, int, str]  # (filename, lineno, funcname)


def _build_tree(raw: Dict[_Key, Any], max_depth: int = 40) -> Optional[Dict[str, Any]]:
    """Convert a pstats raw stats dict into a d3-flamegraph tree.

    ``raw`` is ``{(file, line, func): (pcalls, ncalls, tt, ct, callers)}``.
    We build the tree by following ``callers``: for each function, find
    all functions that *called* it and treat those as children.
    """
    if not raw:
        return None

    # Build inverted index: caller_key → list of callee_keys it called
    called_by: Dict[_Key, List[_Key]] = {k: [] for k in raw}
    for callee, (_pc, _nc, _tt, _ct, callers) in raw.items():
        for caller in callers:
            if caller in called_by:
                called_by[caller].append(callee)

    # A root is a key that is never listed as a callee (nobody called it)
    all_callees = {callee for callees in called_by.values() for callee in callees}
    roots = [k for k in raw if k not in all_callees]

    if not roots:
        # Fallback: pick the function with the highest cumulative time
        roots = [max(raw, key=lambda k: raw[k][3])]

    def build(key: _Key, depth: int, visited: frozenset) -> Optional[Dict[str, Any]]:
        if depth > max_depth or key in visited:
            return None
        _pc, _nc, _tt, ct, _callers = raw[key]
        ms = round(ct * 1000.0, 2)
        if ms < 0.05:
            return None
        file, line, func = key
        basename = file.rsplit("/", 1)[-1] if file else file
        label = f"{func} ({basename}:{line})" if basename else func

        children = []
        for child_key in sorted(called_by.get(key, []), key=lambda k: raw[k][3], reverse=True):
            child = build(child_key, depth + 1, visited | {key})
            if child is not None:
                children.append(child)

        node: Dict[str, Any] = {"name": label, "value": ms, "file": file, "line": line}
        if children:
            node["children"] = children
        return node

    if len(roots) == 1:
        tree = build(roots[0], 0, frozenset())
        if tree:
            tree["name"] = "root"
        return tree

    # Multiple roots → synthetic parent
    children = []
    for r in sorted(roots, key=lambda k: raw[k][3], reverse=True):
        node = build(r, 0, frozenset())
        if node:
            children.append(node)

    if not children:
        return None

    total = sum(c["value"] for c in children)
    return {"name": "root", "value": total, "children": children}


# ── backend ───────────────────────────────────────────────────────────────────

@register
class CProfileBackend(ProfilerBackend):
    """Built-in deterministic profiler — no optional dependencies required.

    Layer: Backend Implementation
    May only import from: ..profiler, standard library, psutil
    """

    name = "cprofile"

    def __init__(self, timeline_interval: float = 0.5) -> None:
        self._profiler: Optional[cProfile.Profile] = None
        self._timeline = _TimelineCollector(interval=timeline_interval)
        self._memory = _MemoryTracker()
        self._t0: float = 0.0

    @classmethod
    def is_available(cls) -> bool:
        return True  # cProfile ships with CPython

    def start(self) -> None:
        self._profiler = cProfile.Profile()
        self._t0 = time.monotonic()
        self._profiler.enable()
        self._timeline.start()
        self._memory.start()

    def stop(self) -> ProfileData:
        if self._profiler is None:
            raise RuntimeError("CProfileBackend.stop() called before start()")

        self._profiler.disable()
        duration = time.monotonic() - self._t0
        timeline = self._timeline.stop()
        memory_tree = self._memory.stop()

        # ── extract stats ─────────────────────────────────────────────────────
        call_tree: Optional[Dict[str, Any]] = None
        sample_count = 0

        try:
            stream = io.StringIO()
            stats = pstats.Stats(self._profiler, stream=stream)
            stats.sort_stats("cumulative")
            sample_count = int(stats.total_calls)

            # pstats.Stats.stats: dict of (file, line, func) → (pcalls, ncalls, tt, ct, callers)
            raw: Dict[_Key, Any] = stats.stats  # type: ignore[attr-defined]
            call_tree = _build_tree(raw)
        except Exception:
            call_tree = None

        # ── aggregate timeline stats ──────────────────────────────────────────
        cpus = [p["cpu_pct"] for p in timeline] if timeline else [0.0]
        mems = [p["rss_mb"] for p in timeline] if timeline else [0.0]

        return ProfileData(
            backend=self.name,
            duration=duration,
            sample_count=sample_count,
            call_tree=call_tree,
            timeline=timeline,
            peak_cpu_pct=max(cpus),
            peak_rss_mb=max(mems),
            avg_cpu_pct=sum(cpus) / len(cpus),
            avg_rss_mb=sum(mems) / len(mems),
            memory_tree=memory_tree,
            peak_disk_read_mb_s=max((p.get("disk_read_mb_s", 0.0) for p in timeline), default=0.0),
            peak_disk_write_mb_s=max((p.get("disk_write_mb_s", 0.0) for p in timeline), default=0.0),
            peak_net_recv_mb_s=max((p.get("net_recv_mb_s", 0.0) for p in timeline), default=0.0),
            peak_net_sent_mb_s=max((p.get("net_sent_mb_s", 0.0) for p in timeline), default=0.0),
            peak_gpu_pct=max((p.get("gpu_pct", 0.0) for p in timeline), default=0.0),
            peak_gpu_mem_mb=max((p.get("gpu_mem_mb", 0.0) for p in timeline), default=0.0),
        )
