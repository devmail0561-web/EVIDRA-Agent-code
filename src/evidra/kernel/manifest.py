# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Manifeste de plugin (T1.2, noyau stdlib — ADR-0004).

Validation minimale structurelle, sans Pydantic : le schéma riche est vérifié
au bord (`directive/`, T4.1). Manifeste absent ou incomplet ⇒ refus
fail-closed avec motif (`ManifestError`).

Rattaché à T1.6 : la hiérarchie d'erreurs unifiée y sera définie ; en
attendant, `ManifestError` dérive de `ValueError`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from evidra.kernel.contracts import CostHint, Verb

_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)
_VERSION = re.compile(r"^\d+(?:\.\d+)*$")


class ManifestError(ValueError):
    """Manifeste absent, incomplet ou mal formé (refus fail-closed)."""


@dataclass(frozen=True, slots=True)
class Permission:
    """Un verbe demandé sur un périmètre (`*` = tous périmètres)."""

    verb: Verb
    scope: str


@dataclass(frozen=True, slots=True)
class Manifest:
    """Déclaration obligatoire d'un plugin (outil ou adaptateur)."""

    name: str
    version: str  # semver
    harness_required: str  # ex. "1.0"
    permissions: frozenset[Permission]
    channels: tuple[str, ...]
    cost_hint: CostHint
    input_schema: Mapping[str, Any]
    output_schema: Mapping[str, Any]
    requires_network: bool


def parse_version(text: str) -> tuple[int, ...] | None:
    """`'1.0'` → `(1, 0)` ; `None` si mal formé (comparaison T1.3)."""
    if not isinstance(text, str) or _VERSION.match(text) is None:
        return None
    return tuple(int(part) for part in text.split("."))


def _exige_str(data: Mapping[str, Any], champ: str, *, non_vide: bool = True) -> str:
    valeur = data.get(champ)
    if not isinstance(valeur, str) or (non_vide and not valeur):
        raise ManifestError(f"manifeste invalide : {champ!r} doit être une chaîne non vide")
    return valeur


def _permissions(data: Mapping[str, Any]) -> frozenset[Permission]:
    brutes = data.get("permissions")
    if not isinstance(brutes, (list, tuple)) or not brutes:
        raise ManifestError("manifeste invalide : 'permissions' doit être une liste non vide")
    permissions: set[Permission] = set()
    for i, brute in enumerate(brutes):
        if not isinstance(brute, Mapping):
            raise ManifestError(f"manifeste invalide : permissions[{i}] doit être un objet")
        verbe = brute.get("verb")
        if not isinstance(verbe, str):
            raise ManifestError(f"manifeste invalide : permissions[{i}].verb doit être une chaîne")
        try:
            verb = Verb(verbe)
        except ValueError:
            raise ManifestError(
                f"manifeste invalide : permissions[{i}].verb {verbe!r} inconnu"
            ) from None
        scope = brute.get("scope")
        if not isinstance(scope, str) or not scope:
            raise ManifestError(f"manifeste invalide : permissions[{i}].scope doit être non vide")
        permissions.add(Permission(verb=verb, scope=scope))
    return frozenset(permissions)


def validate_manifest(data: Mapping[str, Any]) -> Manifest:
    """Valide un manifeste brut, lève `ManifestError` avec motif sinon."""
    if not isinstance(data, Mapping):
        raise ManifestError("manifeste invalide : objet attendu")
    nom = _exige_str(data, "name")
    version = _exige_str(data, "version")
    if _SEMVER.match(version) is None:
        raise ManifestError(f"manifeste invalide : {version!r} n'est pas semver")
    requis = _exige_str(data, "harness_required")
    if parse_version(requis) is None:
        raise ManifestError(f"manifeste invalide : harness_required {requis!r} mal formé")
    canaux = data.get("channels")
    if (
        not isinstance(canaux, (list, tuple))
        or not canaux
        or not all(isinstance(c, str) and c for c in canaux)
    ):
        raise ManifestError("manifeste invalide : 'channels' doit être une liste non vide")
    cout = data.get("cost_hint")
    if not isinstance(cout, Mapping):
        raise ManifestError("manifeste invalide : 'cost_hint' doit être un objet")
    try:
        hint = CostHint(
            ms=float(cout.get("ms", 0.0)),
            calls=int(cout.get("calls", 1)),
        )
    except (TypeError, ValueError):
        raise ManifestError("manifeste invalide : 'cost_hint' mal formé") from None
    for champ in ("input_schema", "output_schema"):
        if not isinstance(data.get(champ), Mapping):
            raise ManifestError(f"manifeste invalide : {champ!r} doit être un objet")
    reseau = data.get("requires_network")
    if not isinstance(reseau, bool):
        raise ManifestError("manifeste invalide : 'requires_network' doit être booléen")
    schemas = data
    return Manifest(
        name=nom,
        version=version,
        harness_required=requis,
        permissions=_permissions(data),
        channels=tuple(canaux),
        cost_hint=hint,
        input_schema=schemas["input_schema"],
        output_schema=schemas["output_schema"],
        requires_network=reseau,
    )


def manifest_from_plugin(cls: object) -> Manifest:
    """Extrait et valide le manifeste déclaré en ClassVars ; refus sinon."""
    lues: dict[str, Any] = {}
    for champ in (
        "name",
        "version",
        "harness_required",
        "permissions",
        "channels",
        "cost_hint",
        "input_schema",
        "output_schema",
        "requires_network",
    ):
        if not hasattr(cls, champ):
            raise ManifestError(
                f"manifeste invalide : {getattr(cls, '__name__', cls)!r} sans {champ!r}"
            )
        lues[champ] = getattr(cls, champ)  # noqa: B009 — présence vérifiée ci-dessus
    permissions = lues["permissions"]
    if isinstance(permissions, frozenset) and all(isinstance(p, Permission) for p in permissions):
        lues["permissions"] = [{"verb": p.verb.value, "scope": p.scope} for p in permissions]
    cout = lues["cost_hint"]
    if isinstance(cout, CostHint):
        lues["cost_hint"] = {"ms": cout.ms, "calls": cout.calls}
    return validate_manifest(lues)
