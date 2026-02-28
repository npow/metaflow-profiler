"""Structural tests — enforce the layered architecture.

No upward imports: a lower layer must never import from a higher layer.

Layer order (low → high):
  profiler (ABC)  →  profilers/* (backends)  →  profile_decorator  →  cards/

These tests parse the source with ``ast`` to check imports statically.
They do not execute the code, so they run without any optional deps.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PLUGINS_DIR = (
    Path(__file__).parent.parent.parent
    / "src" / "metaflow_extensions" / "profiler" / "plugins"
)


def _imports(path: Path) -> set[str]:
    """Return the set of dotted module names imported (directly) by *path*."""
    source = path.read_text()
    tree = ast.parse(source)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _src_imports(path: Path) -> set[str]:
    """Only return imports that are from the metaflow_extensions.profiler namespace."""
    all_imp = _imports(path)
    return {i for i in all_imp if "profiler" in i and "metaflow_extensions" in i}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check_no_import_from(source_path: Path, forbidden_substrings: list[str]) -> None:
    imported = _imports(source_path)
    for imp in imported:
        for forbidden in forbidden_substrings:
            assert forbidden not in imp, (
                f"{source_path.name} must not import from {forbidden!r}. "
                f"Found: {imp!r}"
            )


# ── Structural tests ──────────────────────────────────────────────────────────

@pytest.mark.structural
class TestLayerBoundaries:

    def test_profiler_abc_does_not_import_registry(self):
        """profiler.py (ABC) must not import from the registry."""
        _check_no_import_from(
            PLUGINS_DIR / "profiler.py",
            ["profilers", "profile_decorator", "cards"],
        )

    def test_profiler_abc_does_not_import_decorator(self):
        _check_no_import_from(
            PLUGINS_DIR / "profiler.py",
            ["profile_decorator"],
        )

    def test_registry_does_not_import_decorator(self):
        _check_no_import_from(
            PLUGINS_DIR / "profilers" / "__init__.py",
            ["profile_decorator", "cards"],
        )

    def test_pyinstrument_backend_does_not_import_decorator(self):
        _check_no_import_from(
            PLUGINS_DIR / "profilers" / "pyinstrument.py",
            ["profile_decorator", "cards"],
        )

    def test_cprofile_backend_does_not_import_decorator(self):
        _check_no_import_from(
            PLUGINS_DIR / "profilers" / "cprofile_backend.py",
            ["profile_decorator", "cards"],
        )

    def test_collectors_does_not_import_decorator_or_card(self):
        """_collectors.py must stay in the backend layer."""
        _check_no_import_from(
            PLUGINS_DIR / "profilers" / "_collectors.py",
            ["profile_decorator", "cards", "profile_card"],
        )

    def test_backends_do_not_import_card(self):
        backends = (PLUGINS_DIR / "profilers").glob("*.py")
        for backend_path in backends:
            if backend_path.name == "__init__.py":
                continue
            _check_no_import_from(backend_path, ["cards", "profile_card"])

    def test_decorator_does_not_import_card_internals(self):
        """The decorator may auto-inject a CardDecorator from metaflow core,
        but must not import from our own cards/ package."""
        _check_no_import_from(
            PLUGINS_DIR / "profile_decorator.py",
            ["metaflow_extensions.profiler.plugins.cards"],
        )

    def test_card_does_not_import_decorator(self):
        """The card renderer must not depend on the decorator layer."""
        _check_no_import_from(
            PLUGINS_DIR / "cards" / "profile_card" / "card.py",
            ["profile_decorator"],
        )

    def test_card_does_not_import_backends(self):
        """The card renderer must not depend on backend implementations."""
        _check_no_import_from(
            PLUGINS_DIR / "cards" / "profile_card" / "card.py",
            ["profilers"],
        )


@pytest.mark.structural
class TestNaming:
    """Sanity-check that all required names are present."""

    def test_profile_card_type(self):
        from metaflow_extensions.profiler.plugins.cards.profile_card.card import ProfileCard
        assert ProfileCard.type == "profile_card"

    def test_decorator_name(self):
        from metaflow_extensions.profiler.plugins.profile_decorator import ProfileCardDecorator
        assert ProfileCardDecorator.name == "profile_card"

    def test_cprofile_backend_name(self):
        from metaflow_extensions.profiler.plugins.profilers.cprofile_backend import CProfileBackend
        assert CProfileBackend.name == "cprofile"

    def test_pyinstrument_backend_name(self):
        from metaflow_extensions.profiler.plugins.profilers.pyinstrument import PyinstrumentBackend
        assert PyinstrumentBackend.name == "pyinstrument"

    def test_cards_package_exposes_list(self):
        from metaflow_extensions.profiler.plugins.cards.profile_card import CARDS
        assert isinstance(CARDS, list)
        assert len(CARDS) == 1
        assert CARDS[0].type == "profile_card"
