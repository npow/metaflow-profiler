"""Abstract profiler interface and data types.

Layer: Core Abstraction
May only import from: standard library

This module defines the data contract shared between all layers.
Nothing above this layer (registry, decorator, card) is imported here.
"""

from __future__ import annotations

import dataclasses
from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import Dict
from typing import List
from typing import Optional


@dataclasses.dataclass
class ProfileData:
    """All data collected during a profiling session.

    Serialisable to a plain dict via ``dataclasses.asdict()`` so it can be
    stored as a Metaflow task artifact and read back by the card renderer.
    """

    #: Name of the backend that produced this data (e.g. "pyinstrument").
    backend: str

    #: Wall-clock duration of the profiled code in seconds.
    duration: float

    #: Number of samples or call-counts collected (backend-dependent).
    sample_count: int

    #: Root node of the call tree in d3-flamegraph format, or None if the
    #: backend does not support call-tree output.
    #:
    #: Format::
    #:
    #:   {
    #:     "name": "root",
    #:     "value": <total_ms: float>,
    #:     "children": [
    #:       {"name": "func (file:line)", "value": <ms>, "children": [...]},
    #:       ...
    #:     ]
    #:   }
    call_tree: Optional[Dict[str, Any]]

    #: System resource samples collected at regular intervals.
    #: Each sample: ``{"ts": <seconds_since_start>, "cpu_pct": float, "rss_mb": float}``.
    timeline: List[Dict[str, float]]

    #: Peak CPU utilisation of the process (%) across the timeline.
    peak_cpu_pct: float

    #: Peak resident-set-size of the process (MiB) across the timeline.
    peak_rss_mb: float

    #: Average CPU utilisation of the process (%) across the timeline.
    avg_cpu_pct: float

    #: Average resident-set-size of the process (MiB) across the timeline.
    avg_rss_mb: float

    # ── Extended metrics (all default to 0 / None for backwards compat) ──────

    #: Memory allocation flamegraph in d3-flamegraph format (values in MB).
    #: Only populated when memray is installed.
    memory_tree: Optional[Dict[str, Any]] = None

    #: Peak disk read throughput (MB/s) across the timeline.
    peak_disk_read_mb_s: float = 0.0

    #: Peak disk write throughput (MB/s) across the timeline.
    peak_disk_write_mb_s: float = 0.0

    #: Peak network receive throughput (MB/s) across the timeline.
    peak_net_recv_mb_s: float = 0.0

    #: Peak network send throughput (MB/s) across the timeline.
    peak_net_sent_mb_s: float = 0.0

    #: Peak GPU utilisation (%) across the timeline.
    peak_gpu_pct: float = 0.0

    #: Peak GPU memory usage (MB) across the timeline.
    peak_gpu_mem_mb: float = 0.0


class ProfilerBackend(ABC):
    """Abstract base class for profiler backends.

    Layer: Core Abstraction
    May only import from: standard library

    Subclasses MUST:
    - Set a unique class-level ``name`` string attribute.
    - Implement ``is_available``, ``start``, and ``stop``.
    - Be decorated with ``@register`` from the registry module.
    - Only import their optional third-party dependency *inside* methods
      (so that the import failure is deferred until ``is_available()`` returns
      ``False``).
    """

    #: Unique identifier used in ``@profile_card(profiler=name)``.
    name: str = ""

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Return True if this backend's optional dependencies are installed."""
        ...

    @abstractmethod
    def start(self) -> None:
        """Start the profiler.  Called just before the step body runs."""
        ...

    @abstractmethod
    def stop(self) -> ProfileData:
        """Stop the profiler and return collected data.

        Called immediately after the step body finishes (or raises).
        Must not raise — return a ``ProfileData`` with zeroed-out fields
        if something went wrong.
        """
        ...
