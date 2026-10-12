# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Tranche verticale gold-219 (T3.9, §21(0)) : 5 nombres avant dimensionnement.

`local_files` conceptuel sur les 219 phrases → `analyze_batch` →
enveloppement `ref/span` → seuils → `ingest` → `validate` sur paires
croisées. Poids d'essai (B1) : les nombres valent même mauvais — ils fondent
les budgets par cycle (T1.5), pas des cibles.

Paires : (i) consistance (triplets EXTRAITS réinterrogés — intégrité ≈ 1.0
exigée, sinon bug pipeline) ; (ii) fidélité gold (triplets GOLD — plancher
qualité) ; (iii) croisées (sans lien — spécificité). Verdicts via la coquille
`verifier_lien` (T3.5), jamais de judging ad hoc.
"""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any

from evidra.engine_bridge.provenance import envelopper
from evidra.engine_bridge.validate import verifier_lien
from evidra.memory.envelope import normaliser_label

SOUS_COMMANDES = {"fr": "analyze", "en": "analyze-en"}  # es : non couvert (pas de lattice)


def charger_gold(chemin: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Gold : fixture slim SA (`phrases`) ou originale t2 (`document.sentences`).

    Retour `(couvertes FR/EN, exclues ES)` avec triplets gold normalisés.
    """
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    if "phrases" in brut:
        items = [
            {
                "id": p["sid"],
                "text": p["text"],
                "lang": p["lang"],
                "triplets": [(t["src"], t["relation"], t["dst"]) for t in p["triplets"]],
            }
            for p in brut["phrases"]
        ]
    else:
        items = []
        for s in brut["document"]["sentences"]:
            noeuds = {n["id"]: n["label"] for n in s["cir"]["nodes"]}
            triplets = [
                (noeuds[e["source"]], e["relation"], noeuds[e["target"]]) for e in s["cir"]["edges"]
            ]
            items.append(
                {"id": s["id"], "text": s["text"], "lang": s["lang"], "triplets": triplets}
            )
    couvertes, exclues = [], []
    for it in items:
        triplets = [(normaliser_label(s), r, normaliser_label(d)) for s, r, d in it["triplets"]]
        phrase = {"sid": it["id"], "texte": it["text"], "lang": it["lang"], "triplets": triplets}
        (couvertes if it["lang"] in SOUS_COMMANDES else exclues).append(phrase)
    return couvertes, exclues


def paires_croisees(
    triplets: list[tuple[str, str, str]], n: int, graine: int = 7
) -> list[tuple[str, str, str]]:
    """Croise src/rel × dst d'une autre phrase, hors triplets gold (déterministe)."""
    hasard = random.Random(graine)
    connus = set(triplets)
    croisees, essais = [], 0
    while len(croisees) < n and essais < n * 50:
        essais += 1
        a, b = hasard.choice(triplets), hasard.choice(triplets)
        candidat = (a[0], a[1], b[2])
        if candidat not in connus and candidat not in croisees and a != b:
            croisees.append(candidat)
    return croisees


def triplets_extraits(cirs: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Triplets d'extraction (consistance) : premier bord de chaque CIR."""
    triplets = []
    for cir in cirs:
        noeuds = {n["id"]: n.get("label", "") for n in cir.get("nodes", []) if isinstance(n, dict)}
        for e in cir.get("edges", []):
            if isinstance(e, (list, tuple)) and len(e) == 3 and isinstance(e[2], dict):
                triplets.append(
                    (
                        normaliser_label(str(noeuds.get(e[0], ""))),
                        str(e[2].get("relation", "")),
                        normaliser_label(str(noeuds.get(e[1], ""))),
                    )
                )
                break
    return triplets


def valider_paires(
    graphe: Any, paires: list[tuple[str, str, str]], *, budget: int = 16, timeout_s: float = 30.0
) -> tuple[list[bool], list[float]]:
    """Chaque paire via `verifier_lien` : `(trouvés, latences_ms)`."""
    trouves, latences = [], []
    for src, _rel, dst in paires:
        debut = time.perf_counter()
        recu = verifier_lien(graphe, src, dst, etiquettes={}, budget=budget, timeout_s=timeout_s)
        latences.append((time.perf_counter() - debut) * 1000.0)
        trouves.append(bool(recu.status.value == "ok" and recu.payload.get("trouve")))
    return trouves, latences


def mesurer_nombres(
    trouves_gold: list[bool],
    trouves_cross: list[bool],
    latences: list[float],
    extraction_s: float,
    n_docs: int,
) -> dict[str, Any]:
    """Les 5 nombres : précision/rappel CONFIRMED, taux UNCONFIRMED, latences, débit."""
    vrais = sum(trouves_gold)
    faux = sum(trouves_cross)
    denom_precision = vrais + faux
    latences_triees = sorted(latences)
    p50 = latences_triees[len(latences_triees) // 2] if latences_triees else 0.0
    p99 = latences_triees[max(0, int(len(latences_triees) * 0.99) - 1)] if latences_triees else 0.0
    return {
        "precision_confirmed": (vrais / denom_precision) if denom_precision else None,
        "rappel_confirmed": (vrais / len(trouves_gold)) if trouves_gold else None,
        "taux_unconfirmed": ((len(trouves_cross) - faux) / len(trouves_cross))
        if trouves_cross
        else None,
        "latence_mediane_ms": round(p50, 3),
        "latence_p99_ms": round(p99, 3),
        "docs_sec": round(n_docs / extraction_s, 1) if extraction_s > 0 else None,
        "vrais_trouves": vrais,
        "faux_trouves": faux,
        "n_gold": len(trouves_gold),
        "n_cross": len(trouves_cross),
    }


def envelopper_phrase(cir: dict[str, Any], sid: str, texte: str) -> dict[str, Any]:
    """Enveloppement gold : ref traçable, hash vérifiable, span synthétique honnête."""
    return envelopper(cir, ref=f"gold:t2:{sid}", texte=texte)
