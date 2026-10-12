# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Moteur d'essai partagé (scaffold) : pipeline légère + lattice réelle ou stub.

Poids BRUTS (seedés, non calibrés — B1) : structure d'extraction honnête,
aucune qualité prétendue. Utilisé par les tests d'intégration, le dogfood et
la tranche verticale. À REMPLACER par le moteur calibré quand B2 se lève
(le registre de modèles T10.6 prendra le relais).

Opt-in explicite (`--essai`, jamais par défaut) : rien en production ne
l'utilise sans le dire.
"""

from __future__ import annotations


def parseur_essai(gcn_bin: str | None = None, sous_commande: str = "analyze"):
    """Lattice Rust si `gcn_bin` présent, sinon stub déterministe (documenté)."""
    if gcn_bin is not None:
        from gcn_python.frontend.bridge import GCNLatticeParser

        return GCNLatticeParser(gcn_bin, sous_commande), True
    from gcn_python.layer1.representation import UDRepresentation

    def rep(lemma: str, i: int) -> UDRepresentation:
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

    class Stub:
        def parse(self, text: str):
            return [rep("clause-a", 0), rep("clause-b", 1)], [None]

    return Stub(), False


def moteur_essai(
    gcn_bin: str | None = None, seed: int = 42, sous_commande: str = "analyze", d_emb: int = 16
):
    """`GCNEngine` minimal + `(moteur, lattice_réelle?)` (d_emb=16 : labels divers)."""
    from gcn_python.constants import NODE_TYPES, RELATION_TYPES, rgcn_n_relations
    from gcn_python.engine import GCNEngine
    from gcn_python.layer1.embedding import WordEmbedding
    from gcn_python.layer1.features import FeatureVocabulary
    from gcn_python.layer2.reference import MLPEncoder
    from gcn_python.layer3.reference import RGCNLayer
    from gcn_python.pipeline.cgnp import CGNPipeline

    vocab = FeatureVocabulary()
    embedding = WordEmbedding(d_emb=d_emb, seed=seed)
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
    parseur, reelle = parseur_essai(gcn_bin, sous_commande)
    return GCNEngine(pipeline, text_parser=parseur), reelle
