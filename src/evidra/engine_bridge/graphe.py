# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Graphe moteur matérialisé par domaine (T3.3) : CIR-noyau seuls.

Construit via la méthode publique `add_cir(cir, "document")` — poids 1.0
(constaté : `SESSION_WEIGHTS`), donc sans distorsion de confiance ; les attrs
sont copiés par le moteur (jamais d'alias). L'enveloppe SA ne traverse jamais
(`cir`, `status`, compteurs restent côté SA — I7). Mise à jour incrémentale
(`ajouter`, appelée à l'ingestion T3.6) ; rafraîchissement par reconstruction
(`materialiser`, sans lecture du cache interne moteur).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from gcn_python.verbalizer.instructions import CausalGraph

from evidra.engine_bridge.provenance import serialiser_span
from evidra.memory.envelope import Envelope, normaliser_label

ORIGINE_DOCUMENT = "document"


def cir_pour_moteur(enveloppe: Envelope) -> dict[str, Any]:
    """Enveloppe → mini-CIR dict (noyau seul, ids = labels normalisés)."""
    cir = enveloppe.cir
    p = cir.provenance
    src, dst = normaliser_label(cir.source), normaliser_label(cir.target)
    span = p.span
    return {
        "source_text": "",
        "nodes": [
            {"id": src, "label": cir.source},
            {"id": dst, "label": cir.target},
        ],
        "edges": [
            [
                src,
                dst,
                {
                    "relation": cir.relation,
                    "confidence": cir.confidence,
                    "explicit": cir.explicit,
                    "negated": cir.negated,
                    "provenance": {
                        "ref": p.ref,
                        "span": serialiser_span(span),
                        "extraction_method": p.extraction_method,
                        "model_version": p.model_version,
                        "extracted_at": p.extracted_at,
                    },
                },
            ]
        ],
    }


def ajouter(graphe: CausalGraph, enveloppe: Envelope) -> None:
    """Ajoute une enveloppe au graphe (incrémental, T3.6).

    Lève `ValueError` (moteur) sur relation inconnue ou extrémité pendante —
    la coquille `reason` (T3.5) convertit en reçu `failed`.
    """
    graphe.add_cir(cir_pour_moteur(enveloppe), ORIGINE_DOCUMENT)


def materialiser(enveloppes: Iterable[Envelope]) -> CausalGraph:
    """Reconstruit un graphe frais (rafraîchissement, jamais de cache lu)."""
    graphe = CausalGraph()
    for enveloppe in enveloppes:
        ajouter(graphe, enveloppe)
    return graphe


def empreinte(graphe: CausalGraph) -> list[tuple[str, str, str, float]]:
    """Vue structurelle triée (comparaison incrémental ≡ rebuild, tests).

    Lit `.edges` (structure publique consommée par `reason`/`verify_path`),
    jamais le cache d'inférence interne du moteur.
    """
    return sorted(
        (str(s), str(d), str(a.get("relation")), float(a.get("confidence", 0.0)))
        for s, d, a, _ in graphe.edges
    )
