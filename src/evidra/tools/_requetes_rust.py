# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Commun aux requêtes Rust (T5.5, privé — pas un outil) : IR + jointure.

`iri_pour()` sérialise des enveloppes (jamais persisté, requête seule).
`preuves_pour()` joint les liens Rust aux enveloppes (ref/span/méthode/…,
quarantinés exclus) et compte les non rattachables (I4 : pas de preuve
sans citation).
"""

from __future__ import annotations

from typing import Any

from evidra.engine_bridge.rust import serialiser_iri
from evidra.memory.envelope import normaliser_label
from evidra.memory.memoire import Memoire, id_triplet


def iri_pour(memo: Memoire, ids: tuple[str, ...] | list[str]) -> dict[str, Any]:
    """Enveloppes désignées → IR dict (ordre déterministe)."""
    aretes = []
    for ident in sorted(ids):
        triplet = memo.par_id.get(ident)
        if triplet is None:
            continue
        enveloppe = memo.entites.get(triplet)
        if enveloppe is None:
            continue
        cir, prov = enveloppe.cir, enveloppe.cir.provenance
        aretes.append(
            (
                cir.source,
                cir.target,
                cir.relation,
                cir.confidence,
                cir.negated,
                {
                    "ref": prov.ref,
                    "span": prov.span,
                    "extraction_method": prov.extraction_method,
                    "model_version": prov.model_version,
                    "extracted_at": prov.extracted_at,
                },
            )
        )
    return serialiser_iri(aretes)


def preuves_pour(memo: Memoire, liens: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """`(preuves, manquantes)` : chaque lien joint ou compté (I4 strict)."""
    ids = []
    valides = 0
    for lien in liens:
        if not isinstance(lien, dict):
            continue
        valides += 1
        src, dst = (
            normaliser_label(str(lien.get("from", ""))),
            normaliser_label(str(lien.get("to", ""))),
        )
        rel = lien.get("relation")
        if isinstance(rel, str) and rel:
            ident = id_triplet((memo.domaine, src, rel, dst))
            if ident in memo.par_id:
                ids.append(ident)
                continue
        for triplet in sorted(memo.paires.get((memo.domaine, src, dst), [])):
            ident = id_triplet(triplet)
            if ident in memo.par_id:
                ids.append(ident)
                break
    preuves = memo.preuves(ids)
    return preuves, valides - len(preuves)
