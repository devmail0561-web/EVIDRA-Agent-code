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

from gcn_python.constants import NODE_TYPES, RELATION_TYPES, rgcn_n_relations
from gcn_python.engine import GCNEngine
from gcn_python.layer1.embedding import WordEmbedding
from gcn_python.layer1.features import FeatureVocabulary
from gcn_python.layer1.representation import UDRepresentation
from gcn_python.layer2.reference import MLPEncoder
from gcn_python.layer3.reference import RGCNLayer
from gcn_python.pipeline.cgnp import CGNPipeline

from evidra.adapters.local_files import AdaptateurFichiers
from evidra.engine_bridge.binaire import trouver_binaire
from evidra.ingestion import traiter_document
from evidra.kernel.contracts import Context, Verb
from evidra.kernel.gate import Policy, Rule
from evidra.memory.memoire import Memoire
from evidra.memory.store import Magasin
from evidra.tools.ingest import OutilIngest, Seuils


def _rep(lemma: str, i: int) -> UDRepresentation:
    return UDRepresentation(
        tokens=[{"lemma": lemma, "pos": "VERB", "dep_rel": "root", "morph": {}}],
        root_lemma=lemma,
        root_pos="VERB",
        root_dep_rel="root",
        root_morph={},
        subject_pos=None,
        has_object=False,
        has_advcl=False,
        has_temporal_obl=False,
        token_span=(i, i + 1),
    )


class _StubParser:
    def parse(self, text: str):
        return [_rep("clause-a", 0), _rep("clause-b", 1)], [None]


def _moteur_essai():
    from gcn_python.frontend.bridge import GCNLatticeParser

    vocab = FeatureVocabulary()
    embedding = WordEmbedding(d_emb=4, seed=42)
    d_eff = vocab.d_clause_effective(embedding.d_emb)
    d_edge = vocab.d_edge_closed_loop(d_eff, len(NODE_TYPES), embedding.d_emb)
    pipeline = CGNPipeline(
        encoder=MLPEncoder(d_clause=d_eff, d_edge=d_edge),
        graph=RGCNLayer(
            d_in=d_eff, d_out=d_eff, n_relations=rgcn_n_relations(len(RELATION_TYPES), False)
        ),
        vocabulary=vocab,
        word_embedding=embedding,
    )
    binaire = trouver_binaire()
    if binaire is None:
        return GCNEngine(pipeline, text_parser=_StubParser())
    return GCNEngine(pipeline, text_parser=GCNLatticeParser(binaire, "analyze"))


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
    moteur = _moteur_essai()
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
