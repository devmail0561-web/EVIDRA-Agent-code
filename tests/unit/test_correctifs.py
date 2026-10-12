# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Correctifs post-J4 : tests directs des nouveautés (garde, lecture, seuils, bornes)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from evidra.adapters.local_files import AdaptateurFichiers
from evidra.boot.demarrage import demarrer
from evidra.engine_bridge import reason as pont_reason
from evidra.engine_bridge import validate as pont_validate
from evidra.engine_bridge.moteur import Moteur
from evidra.engine_bridge.moteur import version_moteur as version_pont
from evidra.ingestion import SourceLocale, traiter_document
from evidra.kernel.contracts import Adapter, Status, ToolResult
from evidra.kernel.scheduler import Budgets, Priorite, Scheduler
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire, memoire_depuis_etat
from evidra.memory.store import Magasin, StoreError, lire_domaine
from evidra.tools._requetes_rust import aretes_pour
from evidra.util import borner as borner_util
from evidra.util import garde, version_moteur


def _ok() -> ToolResult:
    return ToolResult(status=Status.OK, payload={"vrai": True})


def test_garde_succes_passe_plat() -> None:
    recu = garde("outil", _ok)
    assert recu.status is Status.OK and recu.payload == {"vrai": True}


def test_garde_panne_failed_motif_et_stack(caplog: pytest.LogCaptureFixture) -> None:
    def boom() -> ToolResult:
        raise RuntimeError("panne-test")

    with caplog.at_level(logging.ERROR):
        recu = garde("outil", boom)
    assert recu.status is Status.FAILED
    assert recu.payload == {"motif": "panne outil : panne-test"}
    assert any("panne outil outil" in m for m in caplog.messages)


def test_garde_journal_appelant(caplog: pytest.LogCaptureFixture) -> None:
    journal = logging.getLogger("evidra.tools.test_x")

    def boom() -> ToolResult:
        raise RuntimeError("panne-test")

    with caplog.at_level(logging.ERROR):
        garde("test_x", boom, journal=journal)
    assert any(r.name == "evidra.tools.test_x" for r in caplog.records)


def test_version_moteur_reexport_et_chaine() -> None:
    assert version_pont is version_moteur
    assert isinstance(version_moteur(), str)


def test_version_moteur_unknown_sans_metadonnees(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib.metadata

    def absente(_nom: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(importlib.metadata, "version", absente)
    assert version_moteur() == "unknown"


def _noyau(src: str, dst: str, ref: str = "doc://1") -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=0.9,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )


def _memoire() -> Memoire:
    memo = Memoire("code")
    memo.observer(_noyau("Gamma", "Delta", "doc://3"), channel="t", fiabilite=0.9, horodatage="t")
    memo.observer(_noyau("Alpha", "Beta", "doc://1"), channel="t", fiabilite=0.9, horodatage="t")
    memo.observer(_noyau("Beta", "Gamma", "doc://2"), channel="t", fiabilite=0.9, horodatage="t")
    return memo


def test_aretes_pour_trie_deterministe() -> None:
    memo = _memoire()
    premier = aretes_pour(memo, tuple(memo.par_id))
    second = aretes_pour(memo, tuple(reversed(tuple(memo.par_id))))
    assert [(a[0], a[1]) for a in premier] == [(a[0], a[1]) for a in second]
    assert {(a[0], a[1]) for a in premier} == {
        ("Alpha", "Beta"),
        ("Beta", "Gamma"),
        ("Gamma", "Delta"),
    }


def _amorcer(tmp_path: Path) -> Path:
    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps({"agent_id": "t", "domain": "code", "permissions": {"allowed": []}}),
        encoding="utf-8",
    )
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.magasin is not None
    rapport.magasin.close()
    return data


def test_lire_domaine_equivaut_recharger(tmp_path: Path) -> None:
    data = _amorcer(tmp_path)
    memo_lu, ignores_lu = lire_domaine(data, "code")
    with Magasin(data) as magasin:
        charge = magasin.recharger("domains/code")
    memo_re, ignores_re = memoire_depuis_etat("code", charge.etat)
    assert set(memo_lu.entites) == set(memo_re.entites)
    assert ignores_lu == ignores_re


def test_lire_domaine_inconnu(tmp_path: Path) -> None:
    with pytest.raises(StoreError, match="domaine inconnu"):
        lire_domaine(tmp_path, "fantome")


def test_raison_none_moteur_non_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    def absente() -> pont_reason.Raisonneur:
        raise ImportError("pas de moteur")

    monkeypatch.setattr(pont_reason, "_raison_moteur_defaut", absente)
    recu = pont_reason.raisonner_chaine(object(), "a", "b", etiquettes={})
    assert recu.status is Status.FAILED
    assert "moteur non importable" in recu.payload["motif"]


def test_validate_injection_partielle_raison() -> None:
    def raison(*_a: object, **_k: object) -> dict:
        return {"status": "ok", "answer": {"path": [], "confidence": 1.0}}

    recu = pont_validate.verifier_lien(
        object(),
        "a",
        "b",
        etiquettes={},
        raison=raison,
        verificateur=lambda *_a, **_k: (False, "non"),
    )
    assert recu.status is Status.DEGRADE


def test_source_locale_satisfaite(tmp_path: Path) -> None:
    racine = tmp_path / "src"
    racine.mkdir()
    (racine / "n.md").write_text("phrase une.\n", encoding="utf-8")
    adaptateur = AdaptateurFichiers(racine)
    assert isinstance(adaptateur, Adapter)
    assert isinstance(adaptateur.canal, str) and callable(adaptateur.etendue)
    stats = traiter_document(
        adaptateur=adaptateur,
        moteur=None,
        outil=None,  # type: ignore[arg-type] — jamais atteint sans CIRs
        ctx=None,  # type: ignore[arg-type] — idem
        uri="doc://n",
        texte="phrase une.",
    )
    assert stats["phrases"] == 1 and stats["cirs"] == 0


def test_configurer_budgets_applique(tmp_path: Path) -> None:
    _ = tmp_path
    ordonnanceur = Scheduler(Budgets(max_tool_calls=2))
    ordonnanceur.enregistrer(Priorite.P1, lambda: True, _ok)
    ordonnanceur.enregistrer(Priorite.P2, lambda: True, _ok)
    assert len(ordonnanceur.tour().recus) == 2
    ordonnanceur.configurer_budgets(Budgets(max_tool_calls=1))
    rapport = ordonnanceur.tour()
    assert len(rapport.recus) == 1
    assert "budget:max_tool_calls" in rapport.budgets_depasse


def test_borner_util_identique_boucle() -> None:
    from evidra.boucle import borner as borner_boucle

    assert borner_boucle is borner_util
    retenus, tronque = borner_util([{"s": 1}, {"s": 5}], 1, score=lambda d: float(d["s"]))
    assert tronque == 1 and retenus == [{"s": 5}]


def test_moteur_protocol_toujours_importable() -> None:
    assert Moteur is not None
    assert SourceLocale is not None
