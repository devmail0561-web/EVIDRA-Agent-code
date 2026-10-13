# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T10.1 — benchmark agentique MVP : intégrité du corpus + scores + déterminisme.

Corpus figé (`benchmarks/agentique-mvp.json`, graine 42) : 1012 documents
(dont 12 anomalies), 200 claims (100/60/40), 50 chaînes. Runner engine-free
(`scripts/benchmark_agentique.py`) : les scores sont exacts et reproductibles,
jamais des cibles.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent.parent
CORPUS = RACINE / "benchmarks" / "agentique-mvp.json"

sys.path.insert(0, str(RACINE / "scripts"))

from benchmark_agentique import mesurer  # noqa: E402


def _corpus() -> dict:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


def test_corpus_fige() -> None:
    corpus = _corpus()
    assert corpus["graine"] == 42
    assert len(corpus["documents"]) == 1012
    assert len(corpus["claims"]) == 200
    assert len(corpus["chaines"]) == 50
    verdicts = [c["verdict"] for c in corpus["claims"]]
    assert verdicts.count("CONFIRMED") == 100
    assert verdicts.count("UNCONFIRMED") == 60
    assert verdicts.count("CONTRADICTED") == 40
    anomalies = [d for d in corpus["documents"] if d["anomalie"]]
    assert len(anomalies) == 12
    assert all(not d["triplets"] for d in anomalies)


def test_verite_coherente() -> None:
    corpus = _corpus()
    verite = {tuple(t) for d in corpus["documents"] for t in d["triplets"]}
    paires = {(t[0], t[2]) for t in verite}
    for claim in corpus["claims"]:
        t = tuple(claim["triplet"])
        if claim["verdict"] == "CONFIRMED":
            assert t in verite
        elif claim["verdict"] == "UNCONFIRMED":
            assert t not in verite and (t[0], t[2]) not in paires
        else:
            opposes = {"cause": "prevent", "prevent": "cause", "enable": "block", "block": "enable"}
            assert t not in verite
            assert (t[0], opposes[t[1]], t[2]) in verite


def test_scores_parfaits() -> None:
    rapport = mesurer(CORPUS)
    assert rapport["claims"]["exactitude_globale"] == 1.0
    assert rapport["claims"]["bons"] == 200
    assert rapport["chaines"] == {"trouvees": 50, "total": 50}
    assert rapport["flux"]["rappel_quarantaine"] == 1.0
    assert rapport["flux"]["faux_positifs"] == 0
    assert rapport["entites"] == 1400


def test_deterministe_et_rapide() -> None:
    premier = mesurer(CORPUS)
    second = mesurer(CORPUS)
    for cle in ("graine", "documents", "entites", "ingest", "claims", "chaines", "flux"):
        assert premier[cle] == second[cle]
    assert premier["duree_s"] < 30.0
    assert premier["docs_s"] > 100.0
