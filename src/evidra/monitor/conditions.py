# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Conditions de surveillance (T7.1) : fonctions pures sur l'état.

Chaque condition = fonction pure testable sans moteur ni disque :
nouvelles relations regex, haute confiance invalidée, conflit non résolu,
source suspecte (registre T6.3). `Condition` porte sa clé de dédup
(`condition:clé`) consommée par `monitor/alerts.py`. Les conditions
moteur (cycles, lacunes) relèvent des outils `query_*`, pas d'ici.
Regex : motifs validés au chargement (compilables, ≤ 200, sans
quantificateurs imbriqués — anti-ReDoS, entrées bornées aux labels).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Condition:
    """Condition déclenchée : nom, sévérité fermée, clé dédup, détail."""

    nom: str
    severite: str  # info|avertissement|critique (cf. output/alert.py)
    cle: str
    detail: dict[str, Any]


def motif_dangereux(motif: str) -> bool:
    """Heuristique anti-ReDoS : quantificateur imbriqué détecté."""
    try:
        re.compile(motif)
    except re.error:
        return True
    if len(motif) > 200:
        return True
    sans_classes = re.sub(r"\[(?:\\.|[^\]\\])*\]", "", motif)
    return re.search(r"\([^()]*[+*{][^()]*\)[+*{?]", sans_classes) is not None


def nouvelle_relation(triplet: tuple[str, str, str, str], motifs: list[str]) -> Condition | None:
    """Nouvelle relation impliquant un motif surveillé (P1)."""
    _domaine, src, _relation, dst = triplet
    for motif in motifs:
        if motif_dangereux(motif):
            continue
        try:
            touche = re.search(motif, src) is not None or re.search(motif, dst) is not None
        except re.error:
            continue
        if touche:
            return Condition(
                nom="nouvelle_relation_surveillee",
                severite="avertissement",
                cle=f"nouvelle_relation:{motif}:{src}>{dst}",
                detail={"motif": motif, "source": src, "cible": dst},
            )
    return None


def haute_confiance_invalidee(
    triplet: tuple[str, str, str, str],
    statut: str,
    confiance: float,
    *,
    seuil: float,
) -> Condition | None:
    """Relation invalidée alors que sa confiance ≥ seuil (critique)."""
    if statut != "invalidee" or confiance < seuil:
        return None
    _domaine, src, relation, dst = triplet
    return Condition(
        nom="haute_confiance_invalidee",
        severite="critique",
        cle=f"invalidee:{src}:{relation}:{dst}",
        detail={"triplet": list(triplet), "confiance": confiance},
    )


def conflit_non_resolu(
    triplet: tuple[str, str, str, str], statut: str, *, depuis_revisions: int = 1
) -> Condition | None:
    """Conflit EN RÉVISION persistant (avertissement)."""
    if statut != "en_revision":
        return None
    _domaine, src, relation, dst = triplet
    return Condition(
        nom="conflit_non_resolu",
        severite="avertissement",
        cle=f"revision:{src}:{relation}:{dst}",
        detail={"triplet": list(triplet), "revisions": depuis_revisions},
    )


def source_suspecte(ref: str, statut_source: str) -> Condition | None:
    """Source passée `suspect` au registre (contradictions — critique)."""
    if statut_source != "suspect":
        return None
    return Condition(
        nom="source_suspecte",
        severite="critique",
        cle=f"source_suspecte:{ref}",
        detail={"ref": ref},
    )
