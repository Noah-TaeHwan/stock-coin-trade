"""Data source registry: licensing metadata and per-profile switches.

The registry file (config/data_sources.toml) is the single record of which
source may be used where. A source is usable in a profile only when its
`enabled.<profile>` switch is on; the policy check additionally requires that
anything switched on for `public` is verified and redistributable.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

STATUSES = ("verified", "unverified", "rejected")
PERMISSIONS = ("allowed", "conditional", "forbidden", "unknown")
PROFILES = ("local", "public")
DEFAULT_REGISTRY = Path(__file__).resolve().parents[2] / "config" / "data_sources.toml"


class RegistryError(ValueError):
    """The registry file is malformed or breaks the publication policy."""


class SourceNotAllowed(PermissionError):
    """A source was requested in a profile where the registry switches it off."""


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    kind: str
    status: str
    terms_url: str
    checked_on: str
    checked_by: str
    commercial_use: str
    redistribution: str
    modification: str
    attribution: str
    enabled: dict[str, bool]
    rate_limit: str = ""
    rate_limit_source: str = ""
    notes: str = ""

    def allowed_in(self, profile: str) -> bool:
        return bool(self.enabled.get(profile, False))


@dataclass(frozen=True)
class Registry:
    sources: dict[str, Source]

    def get(self, source_id: str) -> Source:
        try:
            return self.sources[source_id]
        except KeyError:
            raise RegistryError(f"unknown data source {source_id!r}") from None

    def enabled(self, profile: str) -> list[Source]:
        return [source for source in self.sources.values() if source.allowed_in(profile)]

    def require(self, source_id: str, profile: str) -> Source:
        source = self.get(source_id)
        if not source.allowed_in(profile):
            raise SourceNotAllowed(f"data source {source_id!r} is switched off for the {profile} profile")
        return source


def policy_problems(registry: Registry) -> list[str]:
    """Why the registry may not be published as is (empty list when it may)."""
    problems = []
    for source in registry.sources.values():
        if not source.allowed_in("public"):
            continue
        if source.status != "verified":
            problems.append(f"{source.id}: enabled for public but status is {source.status}")
        if source.redistribution in ("forbidden", "unknown"):
            problems.append(f"{source.id}: enabled for public but redistribution is {source.redistribution}")
        if not source.attribution.strip():
            problems.append(f"{source.id}: enabled for public without an attribution text")
        if not (source.checked_on and source.checked_by):
            problems.append(f"{source.id}: enabled for public without checked_on/checked_by")
    return problems


def _source(source_id: str, raw: dict) -> Source:
    required = ("name", "kind", "status", "commercial_use", "redistribution", "modification", "attribution", "enabled")
    missing = [key for key in required if key not in raw]
    if missing:
        raise RegistryError(f"{source_id}: missing {', '.join(missing)}")
    if raw["status"] not in STATUSES:
        raise RegistryError(f"{source_id}: status must be one of {STATUSES}")
    for key in ("commercial_use", "redistribution", "modification"):
        if raw[key] not in PERMISSIONS:
            raise RegistryError(f"{source_id}: {key} must be one of {PERMISSIONS}")
    enabled = raw["enabled"]
    if set(enabled) - set(PROFILES) or not all(isinstance(value, bool) for value in enabled.values()):
        raise RegistryError(f"{source_id}: enabled must map {PROFILES} to true/false")
    return Source(
        id=source_id,
        name=raw["name"],
        kind=raw["kind"],
        status=raw["status"],
        terms_url=raw.get("terms_url", ""),
        checked_on=raw.get("checked_on", ""),
        checked_by=raw.get("checked_by", ""),
        commercial_use=raw["commercial_use"],
        redistribution=raw["redistribution"],
        modification=raw["modification"],
        attribution=raw["attribution"],
        enabled={profile: bool(enabled.get(profile, False)) for profile in PROFILES},
        rate_limit=raw.get("rate_limit", ""),
        rate_limit_source=raw.get("rate_limit_source", ""),
        notes=raw.get("notes", ""),
    )


def load(path: str | os.PathLike | None = None) -> Registry:
    """Read the registry (DATA_SOURCES_FILE overrides the repository default)."""
    path = Path(path or os.environ.get("DATA_SOURCES_FILE") or DEFAULT_REGISTRY)
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    sources = {source_id: _source(source_id, body) for source_id, body in raw.get("sources", {}).items()}
    if not sources:
        raise RegistryError(f"{path}: no [sources.*] entries")
    return Registry(sources)
