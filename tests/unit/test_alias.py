# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T6.5 — alias : convergence, brut conservé, candidats, homonymes, CLI."""

from __future__ import annotations

import json
from pathlib import Path

from evidra.boot.demarrage import _table_alias, demarrer
from evidra.directive.loader import charger
from evidra.kernel.contracts import Context
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire, memoire_depuis_etat


def _noyau(source: str, ref: str) -> CirCore:
    return CirCore(
        source=source,
        target="panne",
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


def test_variantes_convergent_brut_conserve() -> None:
    memo = Memoire("code")
    table = {("code", "login"): "auth", ("code", "authentification"): "auth"}
    for i, variante in enumerate(["auth", "login", "AUTHENTIFICATION"]):
        memo.observer(
            _noyau(variante, f"doc://{i}"), channel="t", fiabilite=0.5, horodatage="t", alias=table
        )
    assert len(memo.entites) == 1
    triplet = ("code", "auth", "cause", "panne")
    assert triplet in memo.entites
    assert memo.entites[triplet].confirmation_count == 3
    assert memo.entites[triplet].etiquettes_brutes == ("auth", "panne")


def test_candidat_non_promu_ne_change_rien() -> None:
    memo = Memoire("code", n_confirmee=3)
    memo.observer(_noyau("alpha", "doc://1"), channel="t", fiabilite=0.5, horodatage="t")
    memo.observer(_noyau("beta", "doc://2"), channel="t", fiabilite=0.5, horodatage="t")
    assert len(memo.entites) == 2
    assert memo.candidats_alias() == []
    for i in range(3, 6):
        memo.observer(_noyau("alpha", f"doc://a{i}"), channel="t", fiabilite=0.5, horodatage="t")
        memo.observer(_noyau("beta", f"doc://b{i}"), channel="t", fiabilite=0.5, horodatage="t")
    candidats = memo.candidats_alias()
    assert len(candidats) == 1
    assert candidats[0]["a"] == "alpha" and candidats[0]["b"] == "beta"
    assert candidats[0]["co_confirmations"] == 4
    assert len(memo.entites) == 2  # graphe et index intacts


def test_promu_exclu_des_candidats() -> None:
    memo = Memoire("code", n_confirmee=2)
    for i in range(4):
        memo.observer(_noyau("alpha", f"doc://a{i}"), channel="t", fiabilite=0.5, horodatage="t")
        memo.observer(_noyau("beta", f"doc://b{i}"), channel="t", fiabilite=0.5, horodatage="t")
    table = {("code", "alpha"): "auth", ("code", "beta"): "auth"}
    assert memo.candidats_alias(table) == []


def test_homonymes_inter_domaines_distincts() -> None:
    m1, m2 = Memoire("code"), Memoire("cti")
    m1.observer(_noyau("Auth", "doc://1"), channel="t", fiabilite=0.5, horodatage="t")
    m2.observer(_noyau("Auth", "doc://1"), channel="t", fiabilite=0.5, horodatage="t")
    assert ("code", "auth", "cause", "panne") in m1.entites
    assert ("cti", "auth", "cause", "panne") in m2.entites


def test_brut_survit_rebuild() -> None:
    memo = Memoire("code")
    memo.observer(
        _noyau("Login", "doc://1"),
        channel="t",
        fiabilite=0.5,
        horodatage="t",
        alias={("code", "login"): "auth"},
    )
    triplet = ("code", "auth", "cause", "panne")
    assert memo.entites[triplet].etiquettes_brutes == ("Login", "panne")
    from evidra.memory.envelope import resume

    etat = {"x": {"triplet": list(triplet), "enveloppe": dict(resume(memo.entites[triplet]))}}
    memo2, ignores = memoire_depuis_etat("code", etat)
    assert ignores == 0
    assert memo2.entites[triplet].etiquettes_brutes == ("Login", "panne")


def test_demarrage_cable_aliases_directive(tmp_path: Path) -> None:
    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
                "aliases": {"code": {"auth": ["login", "Authentification"]}},
            }
        ),
        encoding="utf-8",
    )
    table = _table_alias(charger(directive))
    assert table == {("code", "login"): "auth", ("code", "authentification"): "auth"}
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.ingest is not None and rapport.magasin is not None
    ctx = Context(store=rapport.magasin, domain="code")
    rapport.ingest.run(ctx, {"noyaux": [_noyau("login", "doc://1")], "channel": "t"})
    memo = rapport.memoires["code"]
    assert ("code", "auth", "cause", "panne") in memo.entites
    rapport.magasin.close()


def test_cli_aliases(tmp_path: Path, capsys) -> None:
    from evidra.cli import main

    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
                "aliases": {"code": {"auth": ["login"]}},
            }
        ),
        encoding="utf-8",
    )
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.ingest is not None and rapport.magasin is not None
    ctx = Context(store=rapport.magasin, domain="code")
    for i in range(3):
        rapport.ingest.run(ctx, {"noyaux": [_noyau("alpha", f"doc://a{i}")], "channel": "t"})
        rapport.ingest.run(ctx, {"noyaux": [_noyau("beta", f"doc://b{i}")], "channel": "t"})
    rapport.magasin.close()
    assert (
        main(
            ["aliases", "--data-dir", str(data), "--domaine", "code", "--directive", str(directive)]
        )
        == 0
    )
    sorties = json.loads(capsys.readouterr().out)
    assert sorties["promus"] == [{"variante": "login", "canonique": "auth"}]
    assert len(sorties["candidats"]) == 1
    assert sorties["candidats"][0]["a"] == "alpha"
