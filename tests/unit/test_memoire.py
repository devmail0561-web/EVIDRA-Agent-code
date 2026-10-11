# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.6 — Mémoire : nouvelle / confirmation / idempotente, rebuild."""

from __future__ import annotations

from evidra.memory.envelope import CirCore, Provenance, resume
from evidra.memory.memoire import Memoire, appliquer_domaine, memoire_depuis_etat
from evidra.memory.wal import Enregistrement


def _noyau(
    src: str = "Authentification", dst: str = "accès", ref: str = "doc://1", conf: float = 0.87
) -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=conf,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="gcn-core-4.0.0",
            extracted_at="2026-10-11T00:00:00Z",
        ),
    )


def test_nouvelle_puis_idempotente() -> None:
    memo = Memoire("code")
    premiere = memo.observer(
        _noyau(), channel="test", fiabilite=0.5, horodatage="2026-10-11T00:00:00Z"
    )
    assert premiere.sorte == "nouvelle"
    assert premiere.enveloppe.confirmation_count == 1
    assert len(memo.index) == 1
    seconde = memo.observer(
        _noyau(), channel="test", fiabilite=0.5, horodatage="2026-10-11T01:00:00Z"
    )
    assert seconde.sorte == "idempotente"
    assert seconde.enveloppe.confirmation_count == 1  # aucun effet
    assert len(memo.index) == 1


def test_confirmation_autre_ref() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(ref="doc://1"), channel="test", fiabilite=0.5, horodatage="t1")
    issue = memo.observer(_noyau(ref="doc://2"), channel="test", fiabilite=0.5, horodatage="t2")
    assert issue.sorte == "confirmation"
    assert issue.enveloppe.confirmation_count == 2
    assert issue.enveloppe.last_confirmed_at == "t2"
    assert len(memo.entites) == 1 and len(memo.index) == 1


def test_alias_passe_plat_normalise() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(src="AUTH"), channel="test", fiabilite=0.5, horodatage="t1")
    casse = memo.observer(_noyau(src="auth"), channel="test", fiabilite=0.5, horodatage="t2")
    assert casse.sorte == "idempotente"  # casse normalisée : même observation
    table = {("code", "login"): "auth"}
    issue = memo.observer(
        _noyau(src="login", ref="doc://2"),
        channel="test",
        fiabilite=0.5,
        horodatage="t3",
        alias=table,
    )
    assert issue.sorte == "confirmation"  # variante d'alias : autre observation, même triplet
    assert len(memo.entites) == 1


def test_rebuild_depuis_etat() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(), channel="test", fiabilite=0.5, horodatage="t1")
    memo.observer(_noyau(ref="doc://2"), channel="test", fiabilite=0.5, horodatage="t2")
    etat: dict = {}
    for triplet, env in memo.entites.items():
        etat[f"k{len(etat)}"] = {
            "domaine": "code",
            "triplet": list(triplet),
            "observation": "o",
            "enveloppe": dict(resume(env)),
        }
    etat["pourrie"] = {"triplet": "pas-un-triplet"}
    rebuilt, ignores = memoire_depuis_etat("code", etat)
    assert ignores == 1
    assert len(rebuilt.entites) == 1
    assert rebuilt.entites[("code", "authentification", "cause", "acces")].confirmation_count == 2


def test_appliquer_domaine_dernier_gagne() -> None:
    etat: dict = {}
    appliquer_domaine(etat, _enr("add_edge", "o1", ("code", "a", "cause", "b"), 1))
    appliquer_domaine(etat, _enr("confirm", "o2", ("code", "a", "cause", "b"), 2))
    appliquer_domaine(etat, _enr("drop", "o3", ("code", "a", "cause", "b"), 0))
    assert len(etat) == 1
    appliquer_domaine(etat, _enr_tombstone(("code", "a", "cause", "b")))
    assert etat == {}


def _enr(op: str, cle: str, triplet: list, count: int) -> Enregistrement:
    return Enregistrement(
        seq=1,
        ts="t",
        op=op,
        cle=cle,
        donnees={
            "domaine": "code",
            "triplet": triplet,
            "observation": cle,
            "enveloppe": _resume_minimal(count),
        },
    )


def _enr_tombstone(triplet: list) -> Enregistrement:
    return Enregistrement(seq=9, ts="t", op="tombstone", cle="x", donnees={"triplet": triplet})


def _resume_minimal(count: int) -> dict:
    return {
        "cir": {
            "source": "a",
            "target": "b",
            "relation": "cause",
            "confidence": 0.5,
            "explicit": True,
            "negated": False,
            "provenance": {
                "ref": "r",
                "span": "synthetic",
                "extraction_method": "m",
                "model_version": "v",
                "extracted_at": "t",
                "content_sha256": "",
                "published_at": None,
            },
        },
        "status": "nouvelle",
        "confirmation_count": count,
        "last_confirmed_at": None,
        "source_reliability": 0.5,
        "ingest_channel": "",
        "derivation": "extracted",
        "quarantine": None,
        "justifications": [],
    }
