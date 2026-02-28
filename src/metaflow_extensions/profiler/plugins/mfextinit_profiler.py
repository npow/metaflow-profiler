"""Metaflow plugin registration entry point.

Layer: Plugin Registration (top-level entry point)
May only import from: standard library

Metaflow discovers STEP_DECORATORS_DESC at import time via the
metaflow_extensions namespace package convention.
The `mfextinit_*.py` pattern allows cards to live in plugins/cards/
without Metaflow attempting to alias our cards/ directory against its own.
"""

STEP_DECORATORS_DESC = [
    ("profile_card", ".profile_decorator.ProfileCardDecorator"),
]

__mf_promote_submodules__ = ["profile_decorator"]
