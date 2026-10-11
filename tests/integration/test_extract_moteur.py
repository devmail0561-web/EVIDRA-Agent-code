# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.1 — coquille sur vrai moteur : contrat `Moteur` + CIRs provenancés."""

# ruff: noqa: E402 — la garde importorskip précède volontairement les imports
# moteur : sans moteur importable, aucun import ci-dessous ne peut réussir.
from __future__ import annotations

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

from evidra.engine_bridge.extract import extraire
from evidra.engine_bridge.moteur import Moteur
from evidra.kernel.contracts import Status


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


def test_moteur_reel_satisfait_contrat_et_produit() -> None:
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
    moteur = GCNEngine(pipeline, text_parser=_StubParser())
    assert isinstance(moteur, Moteur)
    recu = extraire(
        ["Les ventes baissent donc les prix augmentent."], moteur=moteur, timeout_s=30.0
    )
    assert recu.status is Status.OK
    (cir,) = recu.payload["cirs"]
    assert set(cir["edges"][0][2]["provenance"]) >= {
        "ref",
        "span",
        "extraction_method",
        "model_version",
        "extracted_at",
    }
