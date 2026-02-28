"""pyinstrument backend — statistical sampling with call-tree output.

Layer: Backend Implementation
May only import from: ..profiler (ABC), standard library, pyinstrument, psutil
"""

from __future__ import annotations

import json
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from ..profiler import ProfileData
from ..profiler import ProfilerBackend
from . import register
from ._collectors import _MemoryTracker
from ._collectors import _TimelineCollector


# ── frame conversion ──────────────────────────────────────────────────────────

def _parse_frame_str(frame_str: str):
    """Parse a pyinstrument frame_records frame string.

    Format: "funcname\\x00filename\\x00lineno[\\x01suffix]"
    Returns (funcname, filename, lineno_int).
    """
    parts = frame_str.split("\x00")
    if len(parts) < 3:
        return parts[0] if parts else "<unknown>", "", 0
    funcname = parts[0]
    filename = parts[1]
    # line part may have "\x01lXXX" suffix — strip it
    line_raw = parts[2].split("\x01")[0]
    try:
        lineno = int(line_raw)
    except ValueError:
        lineno = 0
    return funcname, filename, lineno


def _build_tree_from_frame_records(
    frame_records: List[Any],
) -> Optional[Dict[str, Any]]:
    """Build a d3-flamegraph tree from pyinstrument's frame_records format.

    Each record is ([frame_str, ...], timing_float).  The stack runs from
    outermost (index 0 = thread) to innermost (leaf).  We skip the thread
    frame and aggregate timing at each depth level.
    """

    class _Node:
        __slots__ = ("name", "value", "children")

        def __init__(self, name: str) -> None:
            self.name = name
            self.value = 0.0
            self.children: Dict[str, "_Node"] = {}

    root = _Node("root")

    for record in frame_records:
        if not record or len(record) < 2:
            continue
        stack, timing = record[0], record[1]
        ms = (timing or 0.0) * 1000.0

        current = root
        current.value += ms

        # stack[0] is the thread identifier — skip it, start from index 1
        for frame_str in stack[1:]:
            funcname, filename, lineno = _parse_frame_str(frame_str)

            # Skip synthetic / internal frames
            if filename in ("<thread>", "") and funcname in ("", "<thread>"):
                continue

            basename = filename.rsplit("/", 1)[-1] if "/" in filename else filename
            # Omit filename for pseudo-files like <string>, <frozen ...>
            if basename and not basename.startswith("<"):
                label = f"{funcname} ({basename}:{lineno})"
            else:
                label = funcname

            key = f"{funcname}\x00{filename}\x00{lineno}"
            if key not in current.children:
                current.children[key] = _Node(label)
            child = current.children[key]
            child.value += ms
            current = child

    if not root.children:
        return None

    def _to_d3(node: _Node) -> Dict[str, Any]:
        result: Dict[str, Any] = {"name": node.name, "value": round(node.value, 2)}
        children = [
            _to_d3(c) for c in node.children.values() if c.value >= 0.1
        ]
        # sort by value descending for a more readable flamegraph
        children.sort(key=lambda n: n["value"], reverse=True)
        if children:
            result["children"] = children
        return result

    return _to_d3(root)


def _frame_to_d3(frame: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively convert a pyinstrument frame dict → d3-flamegraph node.

    Used for older pyinstrument versions that emit a frame/root_frame tree.
    """
    fn = frame.get("function") or "<unknown>"
    filepath = frame.get("file_path_short") or frame.get("file_path") or ""
    line = frame.get("line_no") or 0
    ms = round((frame.get("time") or 0.0) * 1000.0, 2)

    basename = filepath.rsplit("/", 1)[-1] if filepath else ""
    label = f"{fn} ({basename}:{line})" if basename else fn

    node: Dict[str, Any] = {
        "name": label,
        "value": ms,
        "file": filepath,
        "line": line,
    }

    children = [_frame_to_d3(c) for c in frame.get("children") or []]
    children = [c for c in children if c["value"] >= 0.1]
    if children:
        node["children"] = children

    return node


# ── backend ───────────────────────────────────────────────────────────────────

@register
class PyinstrumentBackend(ProfilerBackend):
    """Statistical sampling profiler backed by pyinstrument.

    - Samples at *sample_interval* seconds (default 1 ms).
    - Collects a system-resource timeline in a background thread via psutil.
    - Converts pyinstrument's session tree to d3-flamegraph JSON.
    - Optionally tracks memory allocations via memray.

    Layer: Backend Implementation
    May only import from: ..profiler, standard library, pyinstrument, psutil
    """

    name = "pyinstrument"

    def __init__(
        self,
        sample_interval: float = 0.001,
        timeline_interval: float = 0.5,
    ) -> None:
        self._sample_interval = sample_interval
        self._timeline = _TimelineCollector(interval=timeline_interval)
        self._memory = _MemoryTracker()
        self._profiler: Any = None

    @classmethod
    def is_available(cls) -> bool:
        try:
            import pyinstrument  # noqa: F401
            return True
        except ImportError:
            return False

    def start(self) -> None:
        from pyinstrument import Profiler

        self._profiler = Profiler(interval=self._sample_interval)
        self._profiler.start()
        self._timeline.start()
        self._memory.start()

    def stop(self) -> ProfileData:
        if self._profiler is None:
            raise RuntimeError("PyinstrumentBackend.stop() called before start()")

        session = self._profiler.stop()
        timeline = self._timeline.stop()
        memory_tree = self._memory.stop()

        # ── build call tree ───────────────────────────────────────────────────
        call_tree: Optional[Dict[str, Any]] = None
        sample_count = 0
        duration = 0.0

        if session is not None:
            duration = session.duration or 0.0
            try:
                raw_json = session.to_json()
                # pyinstrument >= 4.6 returns a dict; older versions return a str
                if isinstance(raw_json, str):
                    raw = json.loads(raw_json)
                else:
                    raw = raw_json
                sample_count = raw.get("sample_count") or 0

                # New format (pyinstrument >= 5.x): frame_records list of (stack, timing)
                frame_records = raw.get("frame_records")
                if frame_records:
                    call_tree = _build_tree_from_frame_records(frame_records)
                else:
                    # Old format: frame / root_frame tree dict
                    root_frame = raw.get("frame") or raw.get("root_frame")
                    if root_frame:
                        call_tree = _frame_to_d3(root_frame)
                        call_tree["name"] = "root"
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
