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


def _ko(motif: str) -> ManifestError:
    return ManifestError(f"manifeste : {motif}")


def _exige_str(data: Mapping[str, Any], champ: str, *, non_vide: bool = True) -> str:
    valeur = data.get(champ)
    if not isinstance(valeur, str) or (non_vide and not valeur):
        raise _ko(f"{champ!r} : chaîne non vide exigée")
    return valeur


def _permissions(data: Mapping[str, Any]) -> frozenset[Permission]:
    brutes = data.get("permissions")
    if not isinstance(brutes, (list, tuple)):
        raise _ko("'permissions' : liste exigée (vide = aucun besoin déclaré)")
    permissions: set[Permission] = set()
    for i, brute in enumerate(brutes):
        if not isinstance(brute, Mapping):
            raise _ko(f"permissions[{i}] : objet exigé")
        verbe = brute.get("verb")
        if not isinstance(verbe, str):
            raise _ko(f"permissions[{i}].verb : chaîne exigée")
        try:
            verb = Verb(verbe)
        except ValueError:
            raise _ko(f"permissions[{i}].verb {verbe!r} inconnu") from None
        scope = brute.get("scope")
        if not isinstance(scope, str) or not scope:
            raise _ko(f"permissions[{i}].scope : non vide exigé")
        permissions.add(Permission(verb=verb, scope=scope))
    return frozenset(permissions)


def _canaux(data: Mapping[str, Any]) -> tuple[str, ...]:
    canaux = data.get("channels")
    if (
        isinstance(canaux, (list, tuple))
        and canaux
        and all(isinstance(c, str) and c for c in canaux)
    ):
        return tuple(canaux)
    raise _ko("'channels' : liste non vide exigée")


def _cout(data: Mapping[str, Any]) -> CostHint:
    cout = data.get("cost_hint")
    if isinstance(cout, Mapping):
        try:
            return CostHint(ms=float(cout.get("ms", 0.0)), calls=int(cout.get("calls", 1)))
        except (TypeError, ValueError):
            pass
    raise _ko("'cost_hint' mal formé")


def validate_manifest(data: Mapping[str, Any]) -> Manifest:
    """Valide un manifeste brut, lève `ManifestError` avec motif sinon."""
    if not isinstance(data, Mapping):
        raise _ko("objet attendu")
    nom = _exige_str(data, "name")
    version = _exige_str(data, "version")
    if _SEMVER.match(version) is None:
        raise _ko(f"{version!r} n'est pas semver")
    requis = _exige_str(data, "harness_required")
    if parse_version(requis) is None:
        raise _ko(f"harness_required {requis!r} mal formé")
    for champ in ("input_schema", "output_schema"):
        if not isinstance(data.get(champ), Mapping):
            raise _ko(f"{champ!r} : objet exigé")
    reseau = data.get("requires_network")
    if not isinstance(reseau, bool):
        raise _ko("'requires_network' : booléen exigé")
    return Manifest(
        name=nom,
        version=version,
        harness_required=requis,
        permissions=_permissions(data),
        channels=_canaux(data),
        cost_hint=_cout(data),
        input_schema=data["input_schema"],
        output_schema=data["output_schema"],
        requires_network=reseau,
    )


def manifest_from_plugin(cls: object) -> Manifest:
    """Extrait et valide le manifeste déclaré en ClassVars ; refus sinon."""
    lues: dict[str, Any] = {}
    _champs = (
        "name",
        "version",
        "harness_required",
        "permissions",
        "channels",
        "cost_hint",
        "input_schema",
        "output_schema",
        "requires_network",
    )
    for champ in _champs:
        if not hasattr(cls, champ):
            raise _ko(f"{getattr(cls, '__name__', cls)!r} sans {champ!r}")
        lues[champ] = getattr(cls, champ)  # noqa: B009 — présence vérifiée ci-dessus
    permissions = lues["permissions"]
    if isinstance(permissions, frozenset) and all(isinstance(p, Permission) for p in permissions):
        lues["permissions"] = [{"verb": p.verb.value, "scope": p.scope} for p in permissions]
    cout = lues["cost_hint"]
    if isinstance(cout, CostHint):
        lues["cost_hint"] = {"ms": cout.ms, "calls": cout.calls}
    return validate_manifest(lues)
