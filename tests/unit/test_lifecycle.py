# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T6.1 — cycle de vie : matrice exhaustive, promotion, stale, WAL."""

from __future__ import annotations

from itertools import product

import pytest

from evidra.memory.envelope import (
    CirCore,
    Derivation,
    Envelope,
    Provenance,
    Statut,
    resume,
)
from evidra.memory.lifecycle import (
    TRANSITIONS,
    confiance_effective,
    fraicheur,
    promouvoir,
    recenser_stales,
    transition,
    vieillir,
)
from evidra.memory.memoire import Memoire, appliquer_domaine


def _enveloppe(statut: Statut = Statut.NOUVELLE, compte: int = 1) -> Envelope:
    noyau = CirCore(
        source="a",
        target="b",
        relation="cause",
        confidence=0.9,
        provenance=Provenance(
            ref="doc://1",
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )
    return Envelope(
        noyau,
        status=statut,
        confirmation_count=compte,
        last_confirmed_at="2026-01-01T00:00:00+00:00",
    )


def test_matrice_exhaustive() -> None:
    for etat, cible in product(Statut, Statut):
        env = _enveloppe(etat)
        ok, motif = transition(env, cible, motif="test")
        if cible in TRANSITIONS[etat]:
            assert ok, f"{etat.value} → {cible.value} licite refusée"
            assert env.status is cible and motif == "test"
        else:
            assert not ok, f"{etat.value} → {cible.value} illicite acceptée"
            assert env.status is etat  # inchangée
            assert motif != ""  # rejet comptable


def test_motif_vide_refuse() -> None:
    env = _enveloppe()
    assert transition(env, Statut.ACTIVE, motif="  ") == (False, "transition sans motif refusée")
    assert env.status is Statut.NOUVELLE


def test_promotion_seuils() -> None:
    assert promouvoir(_enveloppe(Statut.NOUVELLE, 1), n_confirmee=3) is None
    assert promouvoir(_enveloppe(Statut.NOUVELLE, 2), n_confirmee=3) is Statut.ACTIVE
    assert promouvoir(_enveloppe(Statut.ACTIVE, 2), n_confirmee=3) is None
    env = _enveloppe(Statut.ACTIVE, 3)
    assert promouvoir(env, n_confirmee=3) is Statut.CONFIRMEE
    assert env.status is Statut.CONFIRMEE


def test_derivee_jamais_promue() -> None:
    from evidra.memory.envelope import fabriquer_derivee

    noyau = _enveloppe().cir
    derivee = fabriquer_derivee(noyau, "j1", "j2")
    assert derivee.derivation is Derivation.DERIVEE
    assert promouvoir(derivee, n_confirmee=1) is None
    assert derivee.status is Statut.NOUVELLE


def test_vieillir() -> None:
    vieille = _enveloppe(Statut.CONFIRMEE)
    juin = "2026-06-01T00:00:00+00:00"
    assert vieillir(vieille, maintenant_iso=juin, stale_after_days=30) is Statut.STALE
    assert vieille.status is Statut.STALE
    assert (
        vieillir(
            _enveloppe(Statut.CONFIRMEE),
            maintenant_iso="2026-01-10T00:00:00+00:00",
            stale_after_days=30,
        )
        is None
    )
    assert (
        vieillir(
            _enveloppe(Statut.NOUVELLE),
            maintenant_iso="2026-06-01T00:00:00+00:00",
            stale_after_days=30,
        )
        is None
    )
    cassee = _enveloppe(Statut.CONFIRMEE)
    cassee.last_confirmed_at = "2026-01-01T00:00:00"  # naive vs aware ⇒ illisible
    assert vieillir(cassee, maintenant_iso="2026-06-01T00:00:00+00:00", stale_after_days=30) is None


def test_changer_statut_et_rejeu_wal() -> None:
    memo = Memoire("code", n_confirmee=3)
    triplet = ("code", "a", "cause", "b")
    memo.ajouter(triplet, "obs1", _enveloppe())
    ok, _ = memo.changer_statut(triplet, Statut.ACTIVE, motif="2 sources")
    assert ok
    assert memo.entites[triplet].status is Statut.ACTIVE
    assert memo.changer_statut(triplet, Statut.MAINTENUE, motif="x")[0] is False
    assert memo.changer_statut(("code", "x", "cause", "y"), Statut.ACTIVE, motif="x")[0] is False
    capsule = {
        "triplet": list(triplet),
        "observation": "obs1",
        "enveloppe": dict(resume(memo.entites[triplet])),
    }

    class _Enr:
        op = "update_status"
        donnees = capsule

    etat: dict = {}
    appliquer_domaine(etat, _Enr())
    from evidra.memory.memoire import memoire_depuis_etat

    memo2, ignores = memoire_depuis_etat("code", etat)
    assert ignores == 0
    assert memo2.entites[triplet].status is Statut.ACTIVE


def _noyau_ref(ref: str) -> CirCore:
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


def test_ingest_confirme_promeut() -> None:
    memo = Memoire("code", n_confirmee=3)
    horo = "2026-01-01T00:00:00+00:00"
    assert (
        memo.observer(_noyau_ref("doc://1"), channel="t", fiabilite=0.5, horodatage=horo).sorte
        == "nouvelle"
    )
    assert (
        memo.observer(_noyau_ref("doc://2"), channel="t", fiabilite=0.5, horodatage=horo).sorte
        == "confirmation"
    )
    assert memo.entites[("code", "a", "cause", "b")].status is Statut.ACTIVE
    memo.observer(_noyau_ref("doc://3"), channel="t", fiabilite=0.5, horodatage=horo)
    assert memo.entites[("code", "a", "cause", "b")].status is Statut.CONFIRMEE


def test_fraicheur_decroissance() -> None:
    import math

    t0 = "2026-01-01T00:00:00+00:00"
    assert fraicheur(t0, maintenant_iso=t0, t_domaine_jours=30.0) == (1.0, True)
    score, connue = fraicheur(t0, maintenant_iso="2026-01-31T00:00:00+00:00", t_domaine_jours=30.0)
    assert connue and score == pytest.approx(math.exp(-1.0))
    assert fraicheur(None, maintenant_iso=t0, t_domaine_jours=30.0) == (1.0, False)
    assert fraicheur("pas-une-date", maintenant_iso=t0, t_domaine_jours=30.0) == (1.0, False)
    assert fraicheur(t0, maintenant_iso="2025-01-01T00:00:00+00:00", t_domaine_jours=30.0) == (
        1.0,
        True,
    )


def test_fraicheur_horloges_domaine() -> None:
    import math

    t0 = "2026-01-01T00:00:00+00:00"
    for jours in (7.0, 90.0, 365.0):  # CTI, conformité, droit : T simule le domaine
        score, connue = fraicheur(
            t0,
            maintenant_iso="2026-01-01T00:00:00+00:00",
            t_domaine_jours=jours,
        )
        assert (score, connue) == (1.0, True)
        vieux, _ = fraicheur(
            "2025-01-01T00:00:00+00:00",
            maintenant_iso="2026-01-01T00:00:00+00:00",
            t_domaine_jours=jours,
        )
        assert vieux == pytest.approx(math.exp(-365.0 / jours))


def test_confiance_effective_n_modifie_pas_cir() -> None:
    env = _enveloppe(Statut.CONFIRMEE)
    score, connue = confiance_effective(
        env, maintenant_iso="2026-06-01T00:00:00+00:00", t_domaine_jours=30.0
    )
    assert connue is False  # published_at None ⇒ neutre + flag
    assert score == pytest.approx(0.9)
    assert env.cir.confidence == 0.9


def test_recenser_stales() -> None:
    memo = Memoire("code", n_confirmee=3)
    horo = "2026-01-01T00:00:00+00:00"
    memo.observer(_noyau_ref("doc://1"), channel="t", fiabilite=0.5, horodatage=horo)
    memo.observer(_noyau_ref("doc://2"), channel="t", fiabilite=0.5, horodatage=horo)
    fiches = recenser_stales(
        memo.entites,
        maintenant_iso="2026-06-01T00:00:00+00:00",
        stale_after_days=30,
        t_domaine_jours=30.0,
    )
    assert len(fiches) == 1
    assert fiches[0]["triplet"] == ["code", "a", "cause", "b"]
    assert fiches[0]["statut"] == "active"
    fraiches = recenser_stales(
        memo.entites,
        maintenant_iso="2026-01-10T00:00:00+00:00",
        stale_after_days=30,
        t_domaine_jours=30.0,
    )
    assert fraiches == []
