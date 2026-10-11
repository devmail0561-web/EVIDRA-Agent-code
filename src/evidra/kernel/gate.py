# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Porte de permissions (T1.4, noyau stdlib).

`can(outil, verbe, scope)` → `Decision` : chaque appel passe la porte ;
défaut tout-interdit-sauf-`read` ; `forbidden` prioritaire sur `allowed` ;
`delete` exige un motif (qui part au WAL côté scheduler, T4.4) ; aucun
héritage par élargissement (correspondance exacte ou `*`, jamais de
préfixe) ; chaque refus devient un reçu `refused` traçable.

La matrice vient de la directive (objet pur en paramètre) : le noyau ne
connaît ni outils concrets ni périmètres (I2 — les noms reçus sont des
données, jamais écrits en dur).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from evidra.kernel.contracts import Cost, Status, ToolResult, Verb


@dataclass(frozen=True, slots=True)
class Rule:
    """Une règle : outil (`*` = tous), verbe, périmètre (`*` = tous)."""

    tool: str
    verb: Verb
    scope: str


@dataclass(frozen=True, slots=True)
class Policy:
    """Matrice pure fournie par la directive (`allowed`/`forbidden`)."""

    allowed: frozenset[Rule] = frozenset()
    forbidden: frozenset[Rule] = frozenset()


@dataclass(frozen=True, slots=True)
class Decision:
    """Décision de la porte : autorisé + motif (toujours renseigné)."""

    allowed: bool
    motif: str

    def __bool__(self) -> bool:
        return self.allowed


def _vise(regle: Rule, outil: str, verbe: Verb, scope: str) -> bool:
    return regle.verb is verbe and regle.tool in (outil, "*") and regle.scope in (scope, "*")


def can(
    policy: Policy,
    outil: str,
    verbe: Verb,
    scope: str,
    *,
    motif: str = "",
) -> Decision:
    """Décide. Ne lève jamais : entrée malformée = refus motivé."""
    if not isinstance(verbe, Verb):
        return Decision(False, f"verbe inconnu : {verbe!r}")
    if not isinstance(outil, str) or not outil:
        return Decision(False, "outil manquant")
    if not isinstance(scope, str) or not scope:
        return Decision(False, "périmètre vide")
    for regle in policy.forbidden:
        if _vise(regle, outil, verbe, scope):
            return Decision(False, f"interdit : {outil} {verbe.value} {scope}")
    for regle in policy.allowed:
        if _vise(regle, outil, verbe, scope):
            if verbe is Verb.DELETE and not motif:
                return Decision(False, "delete exige un motif (tracé au WAL)")
            return Decision(True, f"autorisé : {outil} {verbe.value} {scope}")
    if verbe is Verb.READ:
        return Decision(True, "défaut : read autorisé")
    return Decision(False, f"aucune permission : {outil} {verbe.value} {scope}")


def refuse(
    outil: str,
    verbe: Verb,
    scope: str,
    motif: str,
    cost: Cost | None = None,
) -> ToolResult:
    """Construit le reçu `refused` traçable d'un refus de la porte."""
    verbe_nom = verbe.value if isinstance(verbe, Verb) else repr(verbe)
    charge: dict[str, Any] = {
        "outil": outil,
        "verbe": verbe_nom,
        "scope": scope,
        "motif": motif,
    }
    return ToolResult(
        status=Status.REFUSED,
        payload=charge,
        cost=cost if cost is not None else Cost(),
    )
