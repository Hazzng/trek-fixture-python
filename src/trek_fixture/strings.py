"""Small string utilities with deterministic behaviour."""

from __future__ import annotations

import re

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(text: str) -> str:
    """Return a lowercase, hyphen-separated slug for *text*."""
    lowered = text.strip().lower()
    slug = _SLUG_STRIP.sub("-", lowered)
    return slug.strip("-")


def is_palindrome(text: str) -> bool:
    """Return True if *text* reads the same forwards and backwards.

    Comparison ignores case and non-alphanumeric characters.
    """
    cleaned = "".join(ch for ch in text.lower() if ch.isalnum())
    return cleaned == cleaned[::-1]
