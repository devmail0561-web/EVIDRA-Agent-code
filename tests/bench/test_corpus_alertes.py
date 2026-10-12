# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T7.4 — corpus synthétique : précision/rappel mesurés (cibles P≥0.80/R≥0.75).

État honnête : mesuré sur corpus synthétique traçable, pas un SLO opposable.
Le rappel partiel vient d'e09/e11 multi-conditions (documenté, pas masqué).
"""

from __future__ import annotations

import json
from pathlib import Path

from evidra.monitor.conditions import (
    conflit_non_resolu,
    haute_confiance_invalidee,
    nouvelle_relation,
    source_suspecte,
)

CORPUS = Path(__file__).resolve().parent.parent.parent / "benchmarks" / "alertes-corpus.json"

CIBLE_PRECISION = 0.80
CIBLE_RAPPEL = 0.75


def _predites(ev: dict) -> set[str]:
    triplet = tuple(ev["triplet"])
    trouvees = set()
    cond = nouvelle_relation(triplet, ev["motifs"])
    if cond is not None:
        trouvees.add(cond.nom)
    inv = haute_confiance_invalidee(triplet, ev["statut"], ev["confiance"], seuil=0.80)
    if inv is not None:
        trouvees.add(inv.nom)
    conflit = conflit_non_resolu(triplet, ev["statut"])
    if conflit is not None:
        trouvees.add(conflit.nom)
    suspect = source_suspecte("ref", ev["source"])
    if suspect is not None:
        trouvees.add(suspect.nom)
    return trouvees


def mesurer() -> dict[str, float]:
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))["evenements"]
    vp = fp = fn = 0
    for ev in corpus:
        attendues = set(ev["attendues"])
        predites = _predites(ev)
        vp += len(attendues & predites)
        fp += len(predites - attendues)
        fn += len(attendues - predites)
    precision = vp / (vp + fp) if vp + fp else 1.0
    rappel = vp / (vp + fn) if vp + fn else 1.0
    return {"precision": precision, "rappel": rappel, "vp": vp, "fp": fp, "fn": fn}


def test_corpus_mesure() -> None:
    mesure = mesurer()
    print(f"\nmesure alertes : {mesure}")
    assert mesure["precision"] >= CIBLE_PRECISION
    assert mesure["rappel"] >= CIBLE_RAPPEL
