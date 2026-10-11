# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.3 — enveloppe : immuabilité, clés, anti-boucle I6."""

from __future__ import annotations

import dataclasses

import pytest

from evidra.memory.envelope import (
    CirCore,
    CodeSpan,
    Derivation,
    Envelope,
    Provenance,
    Statut,
    Synthetic,
    TokenSpan,
    _span_texte,
    cle_observation,
    cle_triplet,
    confirmer,
    fabriquer_derivee,
    normaliser_label,
)


def _cir(source: str = "Authentification", target: str = "accès", ref: str = "doc://1") -> CirCore:
    return CirCore(
        source=source,
        target=target,
        relation="causes",
        confidence=0.87,
        provenance=Provenance(
            ref=ref,
            span=TokenSpan(10, 20),
            extraction_method="symbolic_rust",
            model_version="gcn-core-4.0.0",
            extracted_at="2026-10-11T00:00:00Z",
        ),
    )


def test_cir_immuable():
    cir = _cir()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cir.confidence = 0.1  # type: ignore[misc]


def test_enveloppe_cir_lecture_seule():
    env = Envelope(_cir())
    assert env.cir.source == "Authentification"
    assert env.status is Statut.NOUVELLE
    with pytest.raises(AttributeError):
        env.cir = _cir()  # type: ignore[misc]


def test_confiance_hors_bornes_refusee():
    base = _cir()
    with pytest.raises(ValueError):
        CirCore(base.source, base.target, base.relation, 1.5, base.provenance)


def test_normaliser_label():
    assert normaliser_label("  Authentification ") == "authentification"
    assert normaliser_label("État AUTH") == "etat auth"
    assert normaliser_label("auth") != normaliser_label("login")


def test_cle_observation_sans_volatiles():
    a = _cir()
    b = dataclasses.replace(
        a, provenance=dataclasses.replace(a.provenance, extracted_at="2030-01-01T00:00:00Z")
    )
    assert cle_observation(a, "code") == cle_observation(b, "code")
    autre_ref = dataclasses.replace(a, provenance=dataclasses.replace(a.provenance, ref="doc://2"))
    assert cle_observation(a, "code") != cle_observation(autre_ref, "code")


def test_cle_triplet_normalisee():
    a = _cir("  AUTH ", " Accès")
    assert cle_triplet(a, "code") == ("code", "auth", "causes", "acces")
    assert cle_triplet(_cir(), "code") != cle_triplet(_cir(), "autre")


def test_derivee_exige_deux_justifications():
    with pytest.raises(ValueError):
        fabriquer_derivee(_cir(), "", "j2")
    with pytest.raises(ValueError):
        fabriquer_derivee(_cir(), "j1", "j1")
    derivee = fabriquer_derivee(_cir(), "obs-1", "obs-2")
    assert derivee.derivation is Derivation.DERIVEE
    assert derivee.justifications == ("obs-1", "obs-2")


def test_i6_derivee_ne_confirme_jamais():
    premisse_a = Envelope(_cir("A", "B", "doc://1"), confirmation_count=2)
    premisse_b = Envelope(_cir("B", "C", "doc://2"), confirmation_count=1)
    cible = CirCore("A", "C", "causes", 0.5, _cir().provenance)
    derivee = fabriquer_derivee(cible, "obs-a", "obs-b")
    assert confirmer(premisse_a, derivee, horodatage="2026-10-11T00:00:00Z") is False
    assert confirmer(premisse_b, derivee, horodatage="2026-10-11T00:00:00Z") is False
    assert (premisse_a.confirmation_count, premisse_b.confirmation_count) == (2, 1)


def test_confirmation_extraite_compte():
    cible = Envelope(_cir(), confirmation_count=1)
    candidat = Envelope(_cir(ref="doc://2"))
    assert confirmer(cible, candidat, horodatage="2026-10-11T01:00:00Z") is True
    assert cible.confirmation_count == 2
    assert cible.last_confirmed_at == "2026-10-11T01:00:00Z"


def test_spans():
    assert _span_texte(TokenSpan(10, 20)) == "t:10:20"
    assert _span_texte(CodeSpan("f.py", 1, 9)) == "c:f.py:1:9"
    assert _span_texte(Synthetic.SYNTHETIC) == "s"
    assert Synthetic.SYNTHETIC.value == "synthetic"
