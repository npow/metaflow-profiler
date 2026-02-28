"""Metaflow card package for profile_card type.

Metaflow's card discovery looks for a ``CARDS`` list in sub-packages of
``metaflow_extensions.<ext>.plugins.cards``.
"""

from .card import ProfileCard

CARDS = [ProfileCard]

__all__ = ["ProfileCard"]
