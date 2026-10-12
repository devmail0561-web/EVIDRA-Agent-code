# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T6.3 — sources : formule, statuts, amorçage, signal, alimentation ingest."""

from __future__ import annotations

import tempfile
from pathlib import Path

from evidra.directive.schema import Provisoire
from evidra.kernel.contracts import Context, Verb
from evidra.kernel.gate import Policy, Rule
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.memory.registres import Registres
from evidra.memory.sources import (
    Compteurs,
    SeuilsSources,
    bilan,
    fiabilite,
    signale,
    taux_confirmation,
    taux_contradiction,
)
from evidra.memory.store import Magasin
from evidra.tools.ingest import OutilIngest, Seuils


def _seuils() -> SeuilsSources:
    return SeuilsSources()


def test_formule_spec() -> None:
    import pytest

    s = _seuils()
    score, statut = fiabilite(Compteurs(10, 9, 0), s)
    assert statut == "trusted" and score == pytest.approx(0.93)
    assert fiabilite(Compteurs(10, 5, 1), s)[1] == "monitored"
    score2, statut2 = fiabilite(Compteurs(10, 9, 2), s)
    assert statut2 == "suspect" and score2 == pytest.approx(0.87)
    assert taux_confirmation(Compteurs(0, 0, 0)) == 0.0
    assert taux_contradiction(Compteurs(0, 0, 0)) == 0.0


def test_plancher_n_min_et_amorcage() -> None:
    assert fiabilite(Compteurs(2, 2, 0), _seuils()) == (0.5, "monitored")
    assert bilan(None, _seuils())["statut"] == "monitored"
    assert bilan({"blocked": True}, _seuils()) == {
        "fiabilite": 0.0,
        "statut": "blocked",
        "compteurs": {"contribuees": 0, "confirmees_indep": 0, "contredites_sup": 0},
    }


def test_depuis_dict_tolerant() -> None:
    assert Compteurs.depuis_dict("pourri") == Compteurs()
    assert Compteurs.depuis_dict({"contribuees": -3, "confirmees_indep": True}) == Compteurs()


def test_signal_basculement_suspect() -> None:
    s = _seuils()
    avant = Compteurs(10, 9, 0)
    apres = Compteurs(10, 9, 2)
    assert signale(avant, apres, s) is True
    assert signale(avant, Compteurs(10, 9, 0), s) is False
    assert signale(apres, Compteurs(10, 9, 3), s) is False  # déjà suspect


def test_seuils_suivent_schema() -> None:
    p = Provisoire()
    assert SeuilsSources() == SeuilsSources(
        poids_confirmation=p.poids_confirmation,
        n_min=p.n_min_source,
        seuil_confiance=p.seuil_confiance_source,
        plafond_contradiction=p.plafond_contradiction,
        seuil_suspect=p.seuil_suspect,
        plancher_surveillee=p.plancher_surveillee,
    )


def _noyau(ref: str) -> CirCore:
    return CirCore(
        source="a",
        target="b",
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


def test_ingest_alimente_compteurs() -> None:
    with Magasin(Path(tempfile.mkdtemp())) as magasin:
        memo = Memoire("code")
        policy = Policy(allowed=frozenset({Rule("ingest", Verb.INGEST, "*")}))
        outil = OutilIngest(
            {"code": memo},
            policy,
            Seuils(min_confiance=0.0, methodes=frozenset({"symbolic_rust"})),
            lambda: "2026-01-01T00:00:00+00:00",
        )
        ctx = Context(store=magasin, domain="code")
        recu = outil.run(ctx, {"noyaux": [_noyau("doc://1"), _noyau("doc://2")], "channel": "t"})
        assert recu.status.value == "ok"
        trouve = magasin.lookup("registry/sources", "doc://1")
        assert trouve is not None and trouve.data["compteurs"]["contribuees"] == 1
        trouve2 = magasin.lookup("registry/sources", "doc://2")
        assert trouve2 is not None and trouve2.data["compteurs"]["confirmees_indep"] == 1


def test_registres_compteurs_types(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        assert registres.compteurs("inconnue") == {}
        registres.noter_compteurs(
            "s", {"contribuees": 6, "confirmees_indep": 5, "contredites_sup": 0}
        )
        assert registres.compteurs("s")["contribuees"] == 6
