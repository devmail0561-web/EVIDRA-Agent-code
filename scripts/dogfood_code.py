#!/usr/bin/env python3
# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Dogfood `code` (T3.8) : ingère le dépôt SA via sa directive, 100 % offline.

Lit `directives/code.dogfood.json` (domaine, source, seuils), fait tourner F1
sur chaque document (lattice Rust réelle + poids d'essai — structure réelle,
poids bruts B1, aucune qualité prétendue), puis répond à 3 requêtes avec
provenance. Sortie : rapport JSON (compteurs + échantillon de réponses).

Usage : `uv run python scripts/dogfood_code.py [--directive ...] [--data-dir ...]`
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE))

from evidra.adapters.local_files import AdaptateurFichiers  # noqa: E402
from evidra.engine_bridge.binaire import trouver_binaire  # noqa: E402
from evidra.ingestion import traiter_document  # noqa: E402
from evidra.kernel.contracts import Context, Verb  # noqa: E402
from evidra.kernel.gate import Policy, Rule  # noqa: E402
from evidra.memory.memoire import Memoire  # noqa: E402
from evidra.memory.store import Magasin  # noqa: E402
from evidra.tools.ingest import OutilIngest, Seuils  # noqa: E402
from tests.essai import moteur_essai  # noqa: E402


def _moteur_essai(binaire: str, sous_commande: str = "analyze"):
    moteur, _reelle = moteur_essai(binaire, sous_commande=sous_commande)
    return moteur


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("--directive", default=str(RACINE / "directives" / "code.dogfood.json"))
    args.add_argument("--data-dir", default="")
    args.add_argument("--sous-commande", default="analyze")
    opts = args.parse_args()
    directive = json.loads(Path(opts.directive).read_text(encoding="utf-8"))
    domaine = directive["domain"]
    source = directive["sources"][0]
    qualite = directive["quality"]
    binaire = trouver_binaire()
    if binaire is None:
        raise SystemExit(
            "gcn introuvable (GCN_BIN, PATH, ou target/release/gcn) — dogfood réel impossible"
        )
    moteur = _moteur_essai(binaire, opts.sous_commande)
    racine_src = Path(source["config"]["path"])
    if not racine_src.is_absolute():
        racine_src = RACINE / racine_src
    adaptateur = AdaptateurFichiers(
        racine_src, motifs=tuple(source["config"].get("glob", ["**/*.md"]))
    )
    memo = Memoire(domaine)
    policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
    seuils = Seuils(
        min_confiance=float(qualite.get("min_confidence", 0.0)),
        methodes=frozenset(
            [qualite["min_extraction_method"]]
            if isinstance(qualite.get("min_extraction_method"), str)
            else qualite.get("min_extraction_method", ["ml_python"])
        ),
    )
    outil = OutilIngest({domaine: memo}, policy, seuils, lambda: "2026-10-11T00:00:00Z")
    data_dir = (
        Path(opts.data_dir) if opts.data_dir else Path(tempfile.mkdtemp(prefix="evidra-dogfood-"))
    )
    magasin = Magasin(data_dir)
    ctx = Context(store=magasin, domain=domaine)
    docs = adaptateur.poll(None)
    total = {
        "documents": len(docs),
        "phrases": 0,
        "cirs": 0,
        "ajoutees": 0,
        "confirmees": 0,
        "idempotentes": 0,
        "dropped": {},
        "inverifiables": 0,
        "invalides": 0,
    }
    echantillon = []
    for doc in docs:
        stats = traiter_document(
            adaptateur=adaptateur,
            moteur=moteur,
            outil=outil,
            ctx=ctx,
            uri=doc.uri,
            texte=doc.text,
            code=doc.uri.endswith(".py"),
            fichier=doc.uri,
        )
        for cle in (
            "phrases",
            "cirs",
            "ajoutees",
            "confirmees",
            "idempotentes",
            "inverifiables",
            "invalides",
        ):
            total[cle] += stats[cle]
        for motif, n in stats["dropped"].items():
            total["dropped"][motif] = total["dropped"].get(motif, 0) + n
        if len(echantillon) < 3:
            echantillon.append(
                {"uri": doc.uri, "stats": {k: stats[k] for k in ("phrases", "cirs", "ajoutees")}}
            )
    reponses = []
    for env in list(memo.entites.values())[:3]:
        ids = memo.index.causes(env.cir.target) + memo.index.effets(env.cir.source)
        reponses.append(
            {
                "question": f"causes/effets de {env.cir.source}/{env.cir.target}",
                "preuves": len(ids),
                "ref": env.cir.provenance.ref,
                "confiance": env.cir.confidence,
            }
        )
    rapport = {
        "directive": opts.directive,
        "domaine": domaine,
        "binaire": binaire,
        "poids": "essai-bruts-B1",
        "total": total,
        "entites": len(memo.entites),
        "echantillon": echantillon,
        "reponses": reponses,
    }
    print(json.dumps(rapport, indent=2, ensure_ascii=False))
    magasin.close()


if __name__ == "__main__":
    main()
