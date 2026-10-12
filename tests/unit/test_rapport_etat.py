# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.8+T5.9 — rapport reproductible, auto-interrogation (status/tâche/cycle)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path

from evidra import etat
from evidra.boucle import Boucle
from evidra.kernel.contracts import Context, Cost, Record, Status, Tool, ToolResult
from evidra.kernel.manifest import manifest_from_plugin
from evidra.kernel.scheduler import Scheduler
from evidra.memory.envelope import CirCore, Provenance, Statut
from evidra.memory.memoire import Memoire
from evidra.memory.registres import Registres
from evidra.memory.store import Magasin
from evidra.tools.report import OutilRapport


def _noyau(src: str, dst: str, ref: str = "doc://1") -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=0.8,
        provenance=Provenance(
            ref=ref, span="synthetic", extraction_method="m", model_version="v", extracted_at="t"
        ),
    )


def _memoire() -> Memoire:
    memo = Memoire("code")
    memo.observer(_noyau("A", "B"), channel="t", fiabilite=0.5, horodatage="t")
    memo.observer(_noyau("C", "D"), channel="t", fiabilite=0.5, horodatage="t")
    memo.entites[("code", "a", "cause", "b")].status = Statut.EN_REVISION
    memo.entites[("code", "c", "cause", "d")].status = Statut.STALE
    return memo


def test_conforme_et_manifeste() -> None:
    assert isinstance(OutilRapport({}), Tool)
    assert manifest_from_plugin(OutilRapport).name == "report"


def test_rapport_json_sections() -> None:
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        ctx = Context(store=magasin, domain="code")
        recu = OutilRapport({"code": _memoire()}).run(
            ctx, {"scope": "code", "format": "json", "chaines": [["A", "B", "X"]]}
        )
    assert recu.status is Status.OK
    sections = recu.payload["sections"]
    assert sections["conflits"]["items"][0]["triplet"][1] == "a"
    assert sections["stales"]["items"][0]["triplet"][1] == "c"
    assert sections["nouvelles"]["items"] == [] and sections["invalidees"] == 0
    assert sections["chaines"] == [{"chaine": ["A", "B", "X"], "couverture": [2, 3]}]


def test_rapport_texte_et_reproductible() -> None:
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        ctx = Context(store=magasin, domain="code")
        outil = OutilRapport({"code": _memoire()})
        premier = outil.run(ctx, {"scope": "code", "format": "texte"})
        second = outil.run(ctx, {"scope": "code", "format": "texte"})
    assert premier.payload == second.payload  # horloge figée : identique
    assert "Conflits ouverts (1, tronqué 0)" in premier.payload["texte"]
    assert "Invalidées : 0." in premier.payload["texte"]


def test_rapport_invalides() -> None:
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        ctx = Context(store=magasin, domain="code")
        outil = OutilRapport({"code": _memoire()})
        assert outil.run(ctx, {"scope": "", "format": "json"}).status is Status.FAILED
        assert outil.run(ctx, {"scope": "code", "format": "xml"}).status is Status.FAILED
        assert outil.run(ctx, {"scope": "inconnu", "format": "json"}).status is Status.FAILED


def test_etat_apercu() -> None:
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        memo = _memoire()
        magasin.append("domains/code", Record(stream="d", op="add", key="k", data={}))
        apercu = etat.apercu(
            magasin, {"code": memo}, demarre_a=time.monotonic() - 5.0, degraded=False
        )
    assert apercu["edges"] == 2 and apercu["domains"] == ["code"] and apercu["nodes"] >= 2
    assert apercu["wal_seq"] == {"domains/code": 1}
    assert apercu["cache"]["code"]["hits"] >= 0
    assert apercu["epoch"] is None and "I1" in apercu["epoch_note"]
    assert apercu["uptime_s"] is not None and apercu["uptime_s"] >= 5.0
    assert apercu["degraded"] is False


def test_etat_tache_conso() -> None:
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        registres = Registres(magasin)
        registres.creer_tache("t1", "ingest", 100.0, "2030-01-01T00:00:00+00:00")

        def _ok() -> ToolResult:
            return ToolResult(status=Status.OK, payload={}, cost=Cost(ms=2.0, calls=1))

        boucle = Boucle(
            domaine="code",
            ordonnanceur=Scheduler(),
            magasin=magasin,
            registres=registres,
            outils={"ingest": _ok},
        )
        boucle.tick()
        fiche = etat.tache(registres, "t1")
    assert fiche is not None
    assert fiche["id"] == "t1" and fiche["etat"] == "done"
    assert (
        fiche["budget"] == 100.0 and fiche["consomme_ms"] == 2.0 and fiche["consomme_appels"] == 1
    )
    assert fiche["restant_ms"] == 98.0 and fiche["deadline"] == "2030-01-01T00:00:00+00:00"
    assert etat.tache(registres, "fantome") is None


def test_etat_cycle() -> None:
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        boucle = Boucle(
            domaine="code",
            ordonnanceur=Scheduler(),
            magasin=magasin,
            registres=Registres(magasin),
            outils={},
        )
        assert boucle.etat_cycle() == {"phase": "attente", "outil_en_cours": None, "tick": 0}
        assert etat.cycle(boucle)["tick"] == 0


def test_rapport_ecarts_t67() -> None:
    from evidra.memory.ecarts import rapport_ecarts

    memo = _memoire()
    ecarts = rapport_ecarts(memo.entites, n_confirmee=memo.seuil_confirmee)
    assert ecarts["entites"] == 2
    assert ecarts["jamais_confirmees"] == 2
    assert ecarts["sous_seuil_confirmee"] == 2
    assert ecarts["tranches"] == {"1": 2, "2": 0, "3-5": 0, "6+": 0}
    with tempfile.TemporaryDirectory() as tmp, Magasin(Path(tmp)) as magasin:
        ctx = Context(store=magasin, domain="code")
        recu = OutilRapport({"code": memo}).run(ctx, {"scope": "code", "format": "json"})
    assert recu.payload["sections"]["ecarts"]["code"]["entites"] == 2
    assert (
        "Écarts code"
        in OutilRapport({"code": memo})
        .run(ctx, {"scope": "code", "format": "texte"})
        .payload["texte"]
    )
