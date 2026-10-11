# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.8 — SLO P1 mesurés (plus des cibles) : insertion, chargement, requêtes."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from evidra.memory.index import Index
from evidra.memory.wal import WAL
from tests.bench.synthetique import construire, requetes


def _appliquer(etat: dict, enr) -> None:
    etat[enr.cle] = dict(enr.donnees)


def mesurer_insertion(n: int = 10_000) -> dict[str, float]:
    index = Index()
    debut = time.perf_counter()
    for i in range(n):
        index.ajouter(
            f"e{i:06d}", f"concept-{i % 5000:04d}", f"concept-{(i + 7) % 5000:04d}", "causes", 0.8
        )
    duree = time.perf_counter() - debut
    return {"aretes": float(n), "secondes": duree, "aretes_sec": n / duree}


def mesurer_chargement(n: int = 100_000) -> dict[str, float]:
    index = construire(n)
    debut = time.perf_counter()
    total = sum(len(index.causes(r)) for r in requetes())
    duree = time.perf_counter() - debut
    return {"aretes": float(n), "secondes": duree, "reponses": float(total)}


def mesurer_requetes_p99(n: int = 100_000) -> dict[str, float]:
    index = construire(n)
    durees = []
    for requete in requetes():
        debut = time.perf_counter()
        index.causes(requete)
        durees.append((time.perf_counter() - debut) * 1000.0)
    durees.sort()
    return {"p99_ms": durees[max(0, int(len(durees) * 0.99) - 1)], "requetes": float(len(durees))}


def mesurer_wal_rejeu(n: int = 100_000, dossier: Path | None = None) -> dict[str, float]:
    with tempfile.TemporaryDirectory() as tmp:
        racine = Path(dossier) if dossier is not None else Path(tmp)
        with WAL(racine / "wal.jsonl") as journal:
            for i in range(n):
                journal.append("add", f"k{i:06d}", {"n": i})
            journal.sync()
            debut = time.perf_counter()
            rapport = journal.relire()
            duree = time.perf_counter() - debut
    assert len(rapport.valides) == n
    return {"lignes": float(n), "secondes": duree, "lignes_sec": n / duree}


def test_slo_insertion_debit() -> None:
    mesure = mesurer_insertion()
    assert mesure["aretes_sec"] > 1000.0


def test_slo_chargement_requetes() -> None:
    assert mesurer_chargement()["secondes"] < 30.0
    assert mesurer_requetes_p99()["p99_ms"] < 50.0


def test_slo_wal_rejeu() -> None:
    assert mesurer_wal_rejeu(20_000)["lignes_sec"] > 1000.0
