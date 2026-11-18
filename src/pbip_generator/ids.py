"""Deterministic identifiers: the same input always yields the same files,
which keeps git diffs between two generations meaningful."""

from __future__ import annotations

import hashlib
import uuid

_NAMESPACE = uuid.UUID("6f1c3c8e-2b7a-4f5e-9d2a-5b1f0c7e9a11")


def stable_uuid(*parts: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, "|".join(parts)))


def stable_name(*parts: str, length: int = 20) -> str:
    """Hex identifier for PBIR pages and visuals (folder-safe)."""
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:length]
