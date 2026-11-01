"""Helpers for bounded nested-field profiles.

The profile is supplied from ingestion metadata, keyed by a dataset version; this
module never scans event rows while answering a query.
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Mapping

from .catalog import nested_field_parts


@dataclass(frozen=True)
class NestedProfile:
    dataset_version: str
    fields: frozenset[str]

    def contains(self, field: str) -> bool:
        return nested_field_parts(field) is not None and field in self.fields


@lru_cache(maxsize=64)
def _profile(dataset_version: str, fields: tuple[str, ...]) -> NestedProfile:
    return NestedProfile(dataset_version=dataset_version, fields=frozenset(fields))


def load_profile(dataset_version: str, fields: Mapping[str, object] | list[str] | tuple[str, ...]) -> NestedProfile:
    """Build/cache a profile from profiler metadata, retaining only safe 1–2 key paths.

    Expected field names are relative to their JSON root (for example ``ep.order.total``)
    or fully qualified as ``ep.order.total``. Arrays and deeper paths are excluded.
    """
    candidates = fields.keys() if isinstance(fields, Mapping) else fields
    safe = []
    for name in candidates:
        value = str(name)
        if not value.startswith(("ep.", "up.")):
            continue
        if nested_field_parts(value):
            safe.append(value)
    return _profile(str(dataset_version), tuple(sorted(set(safe))))


def source_profile(source) -> NestedProfile:
    """Build a cache key from source-registry snapshot metadata and discovered JSON keys."""
    return load_profile(source.snapshot_version, [*(f"ep.{key}" for key in source.ep_keys),
                                                  *(f"up.{key}" for key in source.up_keys)])
