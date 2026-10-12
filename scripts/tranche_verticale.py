#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Tranche verticale gold-219 (T3.9, §21(0)) : les 5 nombres, même mauvais.

`local_files` conceptuel sur les 219 phrases → `analyze_batch` → enveloppement
→ seuils (0.0/ml — mesure, pas production) → `ingest` → `validate` sur paires
croisées. Poids d'essai (B1) : plancher qualité, dimensionnement honnête.
Sortie : JSON daté (`--sortie`, commité comme preuve J3).

Usage : `uv run python scripts/tranche_verticale.py [--gold ...] [--sortie ...]`
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE))

from evidra.engine_bridge.binaire import trouver_binaire  # noqa: E402
from evidra.engine_bridge.extract import extraire  # noqa: E402
from evidra.engine_bridge.graphe import materialiser  # noqa: E402
from evidra.engine_bridge.provenance import vers_noyaux  # noqa: E402
from evidra.kernel.contracts import Context, Verb  # noqa: E402
from evidra.kernel.gate import Policy, Rule  # noqa: E402
from evidra.memory.memoire import Memoire  # noqa: E402
from evidra.memory.store import Magasin  # noqa: E402
from evidra.tools.ingest import OutilIngest, Seuils  # noqa: E402
from tests.bench.tranche import (  # noqa: E402
    SOUS_COMMANDES,
    charger_gold,
    envelopper_phrase,
    mesurer_nombres,
    paires_croisees,
    triplets_extraits,
    valider_paires,
)
from tests.essai import moteur_essai  # noqa: E402

GOLD_DEFAUT = RACINE / "benchmarks" / "gold-219.json"


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--gold", default=str(GOLD_DEFAUT))
    args.add_argument("--sortie", default="")
    opts = args.parse_args()
    couvertes, exclues = charger_gold(Path(opts.gold))
    print(
        f"gold : {len(couvertes)} couvertes (fr/en), {len(exclues)} exclues (es, pas de lattice)",
        flush=True,
    )
    binaire = trouver_binaire()
    moteurs = {
        lang: moteur_essai(binaire, sous_commande=cmd)[0] for lang, cmd in SOUS_COMMANDES.items()
    }
    memo = Memoire("gold")
    policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
    seuils = Seuils(min_confiance=0.0, methodes=frozenset({"ml_python", "symbolic_rust"}))
    outil = OutilIngest({"gold": memo}, policy, seuils, lambda: datetime.now(UTC).isoformat())
    with (
        tempfile.TemporaryDirectory(prefix="evidra-tranche-") as tmp,
        Magasin(Path(tmp)) as magasin,
    ):
        ctx = Context(store=magasin, domain="gold")
        debut_ext = time.perf_counter()
        par_langue: dict[str, list[int]] = {}
        for i, p in enumerate(couvertes):
            par_langue.setdefault(p["lang"], []).append(i)
        cirs: list = [None] * len(couvertes)
        for lang, idxs in par_langue.items():
            recu = extraire(
                [couvertes[i]["texte"] for i in idxs], moteur=moteurs[lang], timeout_s=300.0
            )
            batch = recu.payload["cirs"]
            assert len(batch) == len(idxs), f"batch {lang} incomplet : {len(batch)}/{len(idxs)}"
            for i, cir in zip(idxs, batch, strict=True):
                cirs[i] = cir
        extraction_s = time.perf_counter() - debut_ext
        invalides = 0
        for phrase, cir in zip(couvertes, cirs, strict=True):
            try:
                enrichi = envelopper_phrase(cir, phrase["sid"], phrase["texte"])
                noyaux = vers_noyaux(enrichi)
            except ValueError:
                invalides += 1
                continue
            outil.run(ctx, {"noyaux": noyaux, "channel": "gold:t2"})
        consistance = triplets_extraits(cirs)
        distincts = set(consistance)
        couverts = sum(1 for t in distincts if ("gold", t[0], t[1], t[2]) in memo.entites)
        integrite = (couverts / len(distincts)) if distincts else None
        graphe = materialiser(memo.entites.values())
        triplets_gold = [t for p in couvertes for t in p["triplets"]]
        cross = paires_croisees(triplets_gold, len(triplets_gold))
        trouves_gold, lat1 = valider_paires(graphe, triplets_gold)
        trouves_cross, lat2 = valider_paires(graphe, cross)
        nombres = mesurer_nombres(
            trouves_gold, trouves_cross, lat1 + lat2, extraction_s, len(couvertes)
        )
    rapport = {
        "date": datetime.now(UTC).isoformat(),
        "gold": str(opts.gold),
        "couverture": {
            "incluses": len(couvertes),
            "exclues_es": len(exclues),
            "motif": "pas de lattice es",
        },
        "seuils": {"min_confiance": 0.0, "methodes": ["ml_python", "symbolic_rust"]},
        "poids": "essai-bruts-B1",
        "graphe": {"entites": len(memo.entites)},
        "integrite_consistance": integrite,
        "invalides": invalides,
        "nombres": nombres,
    }
    texte = json.dumps(rapport, indent=2, ensure_ascii=False)
    print(texte)
    if opts.sortie:
        Path(opts.sortie).write_text(texte + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
