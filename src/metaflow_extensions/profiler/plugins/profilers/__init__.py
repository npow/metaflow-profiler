"""Backend registry.

Layer: Registry
May only import from: ..profiler (ABC), standard library

Provides ``register``, ``get_backend``, and ``available_backends``.
All concrete backends self-register via ``@register`` at import time.
"""

from __future__ import annotations

from typing import Dict
from typing import List
from typing import Type

from ..profiler import ProfilerBackend

_REGISTRY: Dict[str, Type[ProfilerBackend]] = {}


def register(cls: Type[ProfilerBackend]) -> Type[ProfilerBackend]:
    """Class decorator that adds *cls* to the global backend registry."""
    if not cls.name:
        raise ValueError(f"{cls.__name__} must define a non-empty `name` attribute")
    _REGISTRY[cls.name] = cls
    return cls


def get_backend(name: str) -> ProfilerBackend:
    """Return an instantiated backend for *name*.

    Raises ``ValueError`` if the name is unknown or the backend's optional
    dependency is not installed.
    """
    if name not in _REGISTRY:
        available = list(_REGISTRY.keys())
        raise ValueError(f"Unknown profiler backend {name!r}. Available: {available}")
    cls = _REGISTRY[name]
    if not cls.is_available():
        raise ValueError(
            f"Profiler backend {name!r} is not available. "
            f"Install its optional dependency: pip install metaflow-profiler[{name}]"
        )
    return cls()


def available_backends() -> Dict[str, bool]:
    """Return a mapping of backend name → whether its deps are installed."""
    return {name: cls.is_available() for name, cls in _REGISTRY.items()}


def default_backend() -> str:
    """Return the name of the best available backend."""
    preference: List[str] = ["pyinstrument", "cprofile"]
    for name in preference:
        if name in _REGISTRY and _REGISTRY[name].is_available():
            return name
    return "cprofile"  # always available


# ── auto-import backends so their @register decorators fire ──────────────────
from . import cprofile_backend as _cprofile  # noqa: E402, F401
from . import pyinstrument as _pyinstrument  # noqa: E402, F401
