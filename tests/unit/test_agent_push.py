# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T9.3 — agent_push : file, validation, plafond, domaine, anti-Sybil."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from evidra.adapters.agent_push import AdaptateurPush, ingerer_pousses
from evidra.kernel.contracts import Adapter, RawDoc
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire
from evidra.security.signing import signer

T0 = "2026-01-01T00:00:00+00:00"
T1 = "2026-01-01T00:02:00+00:00"
SECRET = "cle-agent-1"


def _agent(**champs):
    base = {"agent_id": "a1", "domains": ["code"], "max_confidence_accepted": 0.7, "cle_id": "k1"}
    base.update(champs)
    return SimpleNamespace(**base)


def _cir(**champs):
    cir = {
        "source": "x",
        "target": "y",
        "relation": "cause",
        "confidence": 0.99,
        "provenance": {"ref": "agent://1", "span": "synthetic"},
    }
    cir.update(champs)
    return cir


def _envoi(cir, agent_id="a1", nonce="n1"):
    corps = json.dumps(cir, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return {
        "cir": cir,
        "signature": signer(SECRET, corps, key_id="k1", nonce=nonce, ts=T0),
        "agent_id": agent_id,
    }


def _doc(envoi) -> RawDoc:
    return RawDoc(uri="agent://push/1", text=json.dumps(envoi), channel="agent_push")


def test_conforme_et_file() -> None:
    adaptateur = AdaptateurPush()
    assert isinstance(adaptateur, Adapter)
    assert manifest_from_plugin(AdaptateurPush).name == "agent_push"
    assert adaptateur.requires_network is False
    assert adaptateur.poll(None) == []
    adaptateur.deposer(_envoi(_cir()))
    docs = adaptateur.poll(None)
    assert len(docs) == 1 and docs[0].channel == "agent_push"
    with pytest.raises(ValueError):
        adaptateur.ack("pas-du-json")


def test_valide_plafonne() -> None:
    noyaux, drops = ingerer_pousses(
        [_doc(_envoi(_cir()))],
        domaine="code",
        agents={"a1": _agent()},
        cles={"k1": SECRET},
        maintenant_iso=T1,
        nonces_vus=set(),
    )
    assert drops == {}
    assert len(noyaux) == 1
    agent_id, noyau = noyaux[0]
    assert agent_id == "a1" and isinstance(noyau, CirCore)
    assert noyau.confidence == 0.7  # plafonné au max de l'agent


def test_rejets() -> None:
    agents = {"a1": _agent()}
    cles = {"k1": SECRET}
    base = [_doc(_envoi(_cir()))]
    kw = {
        "domaine": "code",
        "agents": agents,
        "cles": cles,
        "maintenant_iso": T1,
        "nonces_vus": set(),
    }
    assert ingerer_pousses(base, **kw)[1] == {}
    mauvais = dict(_envoi(_cir()))
    mauvais["signature"] = dict(mauvais["signature"])
    mauvais["signature"]["hmac"] = "00"
    assert list(ingerer_pousses([_doc(mauvais)], **{**kw, "nonces_vus": set()})[1]) == [
        "hmac_invalide"
    ]
    assert list(
        ingerer_pousses([_doc(_envoi(_cir(), agent_id="zz"))], **{**kw, "nonces_vus": set()})[1]
    ) == ["'zz'"]
    assert list(
        ingerer_pousses(
            base, domaine="autre", agents=agents, cles=cles, maintenant_iso=T1, nonces_vus=set()
        )[1]
    ) == ["domaine refusé"]
    assert list(
        ingerer_pousses(
            base,
            domaine="code",
            agents={"a1": _agent(cle_id="")},
            cles=cles,
            maintenant_iso=T1,
            nonces_vus=set(),
        )[1]
    ) == ["agent sans clé"]


def _noyau_local(ref: str) -> CirCore:
    return CirCore(
        source="x",
        target="y",
        relation="cause",
        confidence=0.9,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="local_files",
            model_version="v",
            extracted_at="t",
        ),
    )


def test_quarantaine_antisyble() -> None:
    memo = Memoire("code")
    noyaux, _ = ingerer_pousses(
        [_doc(_envoi(_cir(), nonce="q1"))],
        domaine="code",
        agents={"a1": _agent()},
        cles={"k1": SECRET},
        maintenant_iso=T1,
        nonces_vus=set(),
    )
    _, noyau = noyaux[0]
    memo.observer(noyau, channel="agent_push", fiabilite=0.5, horodatage=T0)
    triplet = ("code", "x", "cause", "y")
    memo.entites[triplet].quarantine = "instruction"
    for i in range(2, 5):
        noyaux2, _ = ingerer_pousses(
            [_doc(_envoi(_cir(), nonce=f"q{i}"))],
            domaine="code",
            agents={"a1": _agent()},
            cles={"k1": SECRET},
            maintenant_iso=T1,
            nonces_vus=set(),
        )
        memo.observer(noyaux2[0][1], channel="agent_push", fiabilite=0.5, horodatage=T0)
    assert memo.entites[triplet].quarantine == "instruction"  # N pairs : jamais libérée
    memo.observer(
        _noyau_local("file:///doc.md"), channel="local_files", fiabilite=0.5, horodatage=T0
    )
    assert memo.entites[triplet].quarantine is None  # non-agent : libérée
