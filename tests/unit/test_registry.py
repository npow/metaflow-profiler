"""Unit tests for the backend registry."""

from __future__ import annotations

import pytest

from metaflow_extensions.profiler.plugins.profiler import ProfilerBackend
from metaflow_extensions.profiler.plugins.profilers import _REGISTRY
from metaflow_extensions.profiler.plugins.profilers import available_backends
from metaflow_extensions.profiler.plugins.profilers import default_backend
from metaflow_extensions.profiler.plugins.profilers import get_backend
from metaflow_extensions.profiler.plugins.profilers import register


class TestRegistry:
    def test_cprofile_always_registered(self):
        assert "cprofile" in _REGISTRY

    def test_available_backends_returns_dict(self):
        ab = available_backends()
        assert isinstance(ab, dict)
        assert "cprofile" in ab
        assert ab["cprofile"] is True  # always available

    def test_default_backend_returns_string(self):
        name = default_backend()
        assert isinstance(name, str)
        assert name in _REGISTRY

    def test_get_backend_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown profiler backend"):
            get_backend("nonexistent_backend_xyz")

    def test_get_backend_cprofile_returns_instance(self):
        backend = get_backend("cprofile")
        assert isinstance(backend, ProfilerBackend)

    def test_register_duplicate_overwrites(self):
        """Registering under the same name overwrites the previous entry."""
        original = _REGISTRY.get("cprofile")

        class _Dummy(ProfilerBackend):
            name = "cprofile"

            @classmethod
            def is_available(cls): return False

            def start(self): pass
            def stop(self): ...

        register(_Dummy)
        assert _REGISTRY["cprofile"] is _Dummy
        # Restore original
        _REGISTRY["cprofile"] = original

    def test_register_missing_name_raises(self):
        class _Unnamed(ProfilerBackend):
            name = ""

            @classmethod
            def is_available(cls): return False

            def start(self): pass
            def stop(self): ...

        with pytest.raises(ValueError, match="non-empty"):
            register(_Unnamed)

    def test_pyinstrument_availability_matches_import(self):
        try:
            import pyinstrument  # noqa: F401
            expected = True
        except ImportError:
            expected = False
        assert available_backends().get("pyinstrument") == expected
