"""Shared timeline collector and memory allocation tracker.

Layer: Backend Implementation
May only import from: ..profiler (ABC), standard library, psutil, memray, pynvml

This module is shared by all concrete backends.  It must not import from
the decorator or card layers.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

# ── Timeline collector ────────────────────────────────────────────────────────


class _TimelineCollector:
    """Background daemon thread that polls psutil every *interval* seconds.

    Collects per-sample:
      - ts, cpu_pct, rss_mb         (always, when psutil available)
      - thread_count                (proc.num_threads())
      - disk_read_mb_s, disk_write_mb_s  (proc.io_counters() delta)
      - net_recv_mb_s, net_sent_mb_s     (psutil.net_io_counters() delta)
      - gpu_pct, gpu_mem_mb              (pynvml, when installed + GPU present)

    All fields beyond the base three are gated in try/except — if the
    dependency is unavailable or the OS doesn't support the call, the field
    is simply absent from that sample dict.
    """

    def __init__(self, interval: float = 0.5) -> None:
        self._interval = interval
        self._samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._t0: float = 0.0

    def start(self) -> None:
        try:
            import psutil  # noqa: F401 — verify availability
        except ImportError:
            return  # silently skip; no timeline will be collected
        self._t0 = time.monotonic()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="mf-profile-timeline"
        )
        self._thread.start()

    def stop(self) -> list[dict[str, float]]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        return self._samples

    def _run(self) -> None:
        import psutil

        proc = psutil.Process()
        # Warm up the cpu_percent counter so the first sample is meaningful.
        proc.cpu_percent(interval=None)

        # State for delta-based I/O rate computation.
        prev_disk_read: int | None = None
        prev_disk_write: int | None = None
        prev_net_recv: int | None = None
        prev_net_sent: int | None = None
        prev_ts: float = time.monotonic()

        # Try to initialise GPU access once; keep handle or set to None.
        _nvml_handle: Any = None
        try:
            import pynvml  # type: ignore[import]

            pynvml.nvmlInit()
            _nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except Exception:
            _nvml_handle = None

        while not self._stop.wait(timeout=self._interval):
            try:
                now = time.monotonic()
                dt = now - prev_ts
                prev_ts = now

                ts = round(now - self._t0, 3)
                cpu = round(proc.cpu_percent(interval=None), 1)
                rss = round(proc.memory_info().rss / (1024 * 1024), 2)
                sample: dict[str, float] = {"ts": ts, "cpu_pct": cpu, "rss_mb": rss}

                # Thread count
                with contextlib.suppress(Exception):
                    sample["thread_count"] = float(proc.num_threads())

                # Disk I/O rates (delta bytes / elapsed seconds → MB/s)
                try:
                    io = proc.io_counters()
                    if (
                        prev_disk_read is not None
                        and prev_disk_write is not None
                        and dt > 0
                    ):
                        sample["disk_read_mb_s"] = round(
                            max(0, io.read_bytes - prev_disk_read) / (1024 * 1024) / dt,
                            4,
                        )
                        sample["disk_write_mb_s"] = round(
                            max(0, io.write_bytes - prev_disk_write) / (1024 * 1024) / dt,
                            4,
                        )
                    prev_disk_read = io.read_bytes
                    prev_disk_write = io.write_bytes
                except Exception:
                    pass

                # Network I/O rates
                try:
                    net = psutil.net_io_counters()
                    if net is not None:
                        if (
                            prev_net_recv is not None
                            and prev_net_sent is not None
                            and dt > 0
                        ):
                            sample["net_recv_mb_s"] = round(
                                max(0, net.bytes_recv - prev_net_recv)
                                / (1024 * 1024)
                                / dt,
                                4,
                            )
                            sample["net_sent_mb_s"] = round(
                                max(0, net.bytes_sent - prev_net_sent)
                                / (1024 * 1024)
                                / dt,
                                4,
                            )
                        prev_net_recv = net.bytes_recv
                        prev_net_sent = net.bytes_sent
                except Exception:
                    pass

                # GPU utilisation + memory
                if _nvml_handle is not None:
                    try:
                        import pynvml  # type: ignore[import]

                        util = pynvml.nvmlDeviceGetUtilizationRates(_nvml_handle)
                        mem_info = pynvml.nvmlDeviceGetMemoryInfo(_nvml_handle)
                        sample["gpu_pct"] = float(util.gpu)
                        sample["gpu_mem_mb"] = round(mem_info.used / (1024 * 1024), 2)
                    except Exception:
                        pass

                self._samples.append(sample)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break


# ── Memory allocation tree builder ────────────────────────────────────────────


def _build_memory_tree(records: list[Any]) -> dict[str, Any] | None:
    """Build a d3-flamegraph tree (values in MB) from memray allocation records.

    ``records`` comes from ``FileReader.get_high_watermark_allocation_records()``.
    Each record exposes ``stack_trace()`` (innermost-first) and ``total_memory``
    (bytes).  The stack is reversed so the root is at the top of the flamegraph.
    """

    class _Node:
        __slots__ = ("children", "name", "value")

        def __init__(self, name: str) -> None:
            self.name = name
            self.value = 0.0
            self.children: dict[str, _Node] = {}

    root = _Node("root")

    for record in records:
        # Resolve allocation size in MB
        mb = 0.0
        try:
            mb = (record.total_memory or 0) / (1024 * 1024)
        except AttributeError:
            try:
                mb = (record.size or 0) / (1024 * 1024)
            except Exception:
                continue

        if mb < 0.001:  # skip < 1 KB allocations
            continue

        # Resolve stack — innermost-first; reverse for outermost-first flamegraph
        try:
            stack = list(reversed(list(record.stack_trace())))
        except Exception:
            continue

        current = root
        current.value += mb

        for frame in stack:
            try:
                if hasattr(frame, "function"):
                    funcname = frame.function or "<unknown>"
                    filename = getattr(frame, "filename", "") or ""
                    lineno = getattr(frame, "lineno", 0) or 0
                elif isinstance(frame, (list, tuple)) and len(frame) >= 1:
                    funcname = (frame[0] or "<unknown>") if frame[0] else "<unknown>"
                    filename = frame[1] if len(frame) > 1 else ""
                    lineno = frame[2] if len(frame) > 2 else 0
                else:
                    continue
            except (IndexError, TypeError):
                continue

            basename = filename.rsplit("/", 1)[-1] if "/" in filename else filename
            if basename and not basename.startswith("<"):
                label = f"{funcname} ({basename}:{lineno})"
            else:
                label = funcname

            key = f"{funcname}\x00{filename}\x00{lineno}"
            if key not in current.children:
                current.children[key] = _Node(label)
            child = current.children[key]
            child.value += mb
            current = child

    if not root.children:
        return None

    def _to_d3(node: _Node) -> dict[str, Any]:
        result: dict[str, Any] = {"name": node.name, "value": round(node.value, 4)}
        children = [_to_d3(c) for c in node.children.values() if c.value >= 0.001]
        children.sort(key=lambda n: n["value"], reverse=True)
        if children:
            result["children"] = children
        return result

    return _to_d3(root)


# ── Memory allocation tracker ─────────────────────────────────────────────────


class _MemoryTracker:
    """Optional memory allocation tracker using memray.

    Silently no-ops if memray is not installed.  Call ``start()`` before the
    profiled code and ``stop()`` after; ``stop()`` returns a d3-flamegraph tree
    dict (values in MB) or ``None`` if memray is unavailable or tracking failed.
    """

    def __init__(self) -> None:
        self._tmpfile: Path | None = None
        self._tracker: Any = None
        self._available: bool = False

    def start(self) -> None:
        try:
            import memray  # type: ignore[import]

            fd, path = tempfile.mkstemp(suffix=".bin", prefix="mf-profile-mem-")
            os.close(fd)
            # Remove the empty file so memray can create it fresh.
            os.unlink(path)
            self._tmpfile = Path(path)
            self._tracker = memray.Tracker(str(self._tmpfile))
            self._tracker.__enter__()
            self._available = True
        except Exception:
            self._available = False

    def stop(self) -> dict[str, Any] | None:
        tree = None
        reader = None
        try:
            if not self._available or self._tracker is None:
                return None
            self._tracker.__exit__(None, None, None)
            import memray  # type: ignore[import]

            reader = memray.FileReader(str(self._tmpfile))
            records = list(reader.get_high_watermark_allocation_records(merge_threads=True))
            tree = _build_memory_tree(records)
        except Exception:
            tree = None
        finally:
            # Explicitly release the reader's file handle before unlinking.
            del reader
            if self._tmpfile is not None and self._tmpfile.exists():
                with contextlib.suppress(Exception):
                    self._tmpfile.unlink()
        return tree
