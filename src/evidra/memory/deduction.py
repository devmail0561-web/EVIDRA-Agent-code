# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Déduction tracée (T6.6) : A→B + B→C ⇒ A→C `derived`, pur.

Règles : prémisses EXTRAITE seules (jamais de dérivée) ; même relation
(transitivité homogène) ; A→C absent pour cette relation ; confiance =
`min(prémisses)` (jamais augmentée) ; deux justifications obligatoires
(ids stables) ; span `Synthetic` ; interdite par défaut (`autorise=False`
⇒ `[]`, gate directive `deduction`). Ne confirme jamais ses prémisses
(I6, `confirmer` refuse) et n'entre jamais dans l'extraction moteur
(chemin `extract` : documents seuls, jamais d'enveloppes).
"""

from __future__ import annotations

from evidra.kernel.contracts import HARNESS_VERSION
from evidra.memory.envelope import (
    CirCore,
    Derivation,
    Envelope,
    Provenance,
    Synthetic,
    fabriquer_derivee,
)
from evidra.memory.memoire import id_triplet


def deduire(
    entites: dict[tuple[str, str, str, str], Envelope],
    *,
    autorise: bool,
    horodatage: str,
) -> list[Envelope]:
    """Chaînes A→B→C sans A→C : arêtes `derived` (vide si interdit)."""
    if not autorise:
        return []
    extraites = {t: e for t, e in entites.items() if e.derivation is Derivation.EXTRAITE}
    par_relation: dict[tuple[str, str], list[tuple[str, str, str, str]]] = {}
    for triplet in extraites:
        par_relation.setdefault((triplet[0], triplet[2]), []).append(triplet)
    deduites = []
    for (domaine, relation), triplets in sorted(par_relation.items()):
        sortants: dict[str, list[str]] = {}
        for _, src, _, dst in triplets:
            sortants.setdefault(src, []).append(dst)
        for a in sorted(sortants):
            for b in sorted(sortants[a]):
                for c in sorted(sortants.get(b, [])):
                    if a == c:
                        continue
                    if (domaine, a, relation, c) in extraites:
                        continue
                    t_ab = (domaine, a, relation, b)
                    t_bc = (domaine, b, relation, c)
                    conf = min(extraites[t_ab].cir.confidence, extraites[t_bc].cir.confidence)
                    cible = CirCore(
                        source=a,
                        target=c,
                        relation=relation,
                        confidence=conf,
                        provenance=Provenance(
                            ref=f"derived://{id_triplet(t_ab)[:12]}/{id_triplet(t_bc)[:12]}",
                            span=Synthetic.SYNTHETIC,
                            extraction_method="deduction_sa",
                            model_version=f"sa-{HARNESS_VERSION}",
                            extracted_at=horodatage,
                        ),
                    )
                    deduites.append(fabriquer_derivee(cible, id_triplet(t_ab), id_triplet(t_bc)))
    return deduites
