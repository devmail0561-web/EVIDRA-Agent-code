# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.8 — dogfood `code` : adapter → extract → enveloppe → ingest → requêtes.

Corpus fixture (pas tout le dépôt : rapide, déterministe). Moteur =
pipeline d'essai + lattice Rust si `gcn` présent, sinon parseur stub
(plumbing prouvé dans les deux cas, labels réels seulement avec lattice).
100 % offline : aucun appel réseau (job `offline.yml`).
"""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
from __future__ import annotations

from pathlib import Path

import pytest

gcn_python = pytest.importorskip("gcn_python", reason="moteur non importable")

from evidra.adapters.local_files import AdaptateurFichiers
from evidra.engine_bridge.binaire import trouver_binaire
from evidra.ingestion import traiter_document
from evidra.kernel.contracts import Context, Verb
from evidra.kernel.gate import Policy, Rule
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.ingest import OutilIngest, Seuils
from tests.essai import moteur_essai


def _corpus(racine: Path) -> Path:
    src = racine / "corpus"
    (src / "docs").mkdir(parents=True)
    (src / "docs" / "panne.md").write_text(
        "# Panne\nLa surchauffe grille le moteur donc la pompe s'arrête.\n", encoding="utf-8"
    )
    (src / "docs" / "notes.md").write_text(
        "# Notes\nRien de causal ici, juste du texte.\n", encoding="utf-8"
    )
    (src / "mod.py").write_text(
        '"""Provoque une alerte si chaud."""\nSEUIL = 90\n', encoding="utf-8"
    )
    return src


def test_dogfood_bout_en_bout(tmp_path: Path) -> None:
    moteur, _reelle = moteur_essai(trouver_binaire())
    memo = Memoire("code")
    policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
    seuils = Seuils(min_confiance=0.0, methodes=frozenset({"ml_python", "symbolic_rust"}))
    outil = OutilIngest({"code": memo}, policy, seuils, lambda: "2026-10-11T00:00:00Z")
    adaptateur = AdaptateurFichiers(_corpus(tmp_path), motifs=("**/*.md", "**/*.py"))
    with Magasin(tmp_path / "data") as magasin:
        ctx = Context(store=magasin, domain="code")
        total = {"cirs": 0, "ajoutees": 0, "confirmees": 0}
        docs = adaptateur.poll(None)
        assert len(docs) == 3
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
                timeout_s=60.0,
            )
            total["cirs"] += stats["cirs"]
            total["ajoutees"] += stats["ajoutees"]
            total["confirmees"] += stats["confirmees"]
            assert stats["inverifiables"] == 0
    assert total["cirs"] > 0 and (total["ajoutees"] + total["confirmees"]) > 0
    assert len(memo.entites) > 0
    # Requêtes avec provenance (I4) : chaque réponse cite sa source.
    assert len(memo.index) == len(memo.entites)
    cites = 0
    for env in memo.entites.values():
        assert env.cir.provenance.ref.startswith("file://")
        ids = memo.index.causes(env.cir.target) + memo.index.effets(env.cir.source)
        assert ids != ()
        cites += 1
    assert cites > 0
