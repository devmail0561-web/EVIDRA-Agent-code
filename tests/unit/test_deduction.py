# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T6.6 — déduction : gate, chaîne, min-confiance, anti-boucle I6, CLI."""

from __future__ import annotations

import json
from pathlib import Path

from evidra.boot.demarrage import demarrer
from evidra.kernel.contracts import Context
from evidra.memory.deduction import deduire
from evidra.memory.envelope import (
    CirCore,
    Derivation,
    Provenance,
    Synthetic,
    confirmer,
    fabriquer_derivee,
)
from evidra.memory.memoire import Memoire


def _noyau(source: str, cible: str, ref: str, conf: float = 0.9) -> CirCore:
    return CirCore(
        source=source,
        target=cible,
        relation="cause",
        confidence=conf,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )


def _memoire_chaine() -> Memoire:
    memo = Memoire("code")
    memo.observer(_noyau("a", "b", "doc://1", conf=0.6), channel="t", fiabilite=0.5, horodatage="t")
    memo.observer(_noyau("b", "c", "doc://2"), channel="t", fiabilite=0.5, horodatage="t")
    return memo


def test_interdite_par_defaut() -> None:
    assert deduire(_memoire_chaine().entites, autorise=False, horodatage="t") == []


def test_chaine_deduit_min_justifiee() -> None:
    deduites = deduire(_memoire_chaine().entites, autorise=True, horodatage="t0")
    assert len(deduites) == 1
    derivee = deduites[0]
    assert derivee.derivation is Derivation.DERIVEE
    assert (derivee.cir.source, derivee.cir.target) == ("a", "c")
    assert derivee.cir.confidence == 0.6  # min(prémisses), jamais augmentée
    assert len(derivee.justifications) == 2
    assert derivee.justifications[0] != derivee.justifications[1]
    assert derivee.cir.provenance.span == Synthetic.SYNTHETIC
    assert derivee.cir.provenance.ref.startswith("derived://")


def test_absence_si_lien_direct() -> None:
    memo = _memoire_chaine()
    memo.observer(_noyau("a", "c", "doc://4"), channel="t", fiabilite=0.5, horodatage="t")
    assert deduire(memo.entites, autorise=True, horodatage="t") == []


def test_premisses_derivees_refusees() -> None:
    memo = _memoire_chaine()
    memo.observer(_noyau("d", "a", "doc://0"), channel="t", fiabilite=0.5, horodatage="t")
    premieres = deduire(memo.entites, autorise=True, horodatage="t")
    derivee = next(d for d in premieres if (d.cir.source, d.cir.target) == ("a", "c"))
    memo.ajouter(("code", "a", "cause", "c"), "obs-d", derivee)
    # d→a + a→c(dérivée) ne doit PAS produire d→c : prémisse dérivée refusée.
    suivantes = deduire(memo.entites, autorise=True, horodatage="t")
    assert all(not (d.cir.source == "d" and d.cir.target == "c") for d in suivantes)


def test_anti_boucle_i6() -> None:
    memo = _memoire_chaine()
    (derivee,) = deduire(memo.entites, autorise=True, horodatage="t")
    premisse = memo.entites[("code", "a", "cause", "b")]
    avant_compte, avant_statut = premisse.confirmation_count, premisse.status
    assert confirmer(premisse, derivee, horodatage="t") is False
    assert premisse.confirmation_count == avant_compte
    assert premisse.status is avant_statut


def test_fabrique_exige_deux_justifications() -> None:
    import pytest

    noyau = _noyau("a", "c", "doc://x")
    with pytest.raises(ValueError):
        fabriquer_derivee(noyau, "j1", "j1")
    with pytest.raises(ValueError):
        fabriquer_derivee(noyau, "", "j2")


def test_cli_deduire_gate_et_bout_en_bout(tmp_path: Path, capsys) -> None:
    from evidra.cli import main

    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
            }
        ),
        encoding="utf-8",
    )
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.ingest is not None and rapport.magasin is not None
    ctx = Context(store=rapport.magasin, domain="code")
    rapport.ingest.run(
        ctx,
        {"noyaux": [_noyau("a", "b", "doc://1"), _noyau("b", "c", "doc://2")], "channel": "t"},
    )
    rapport.magasin.close()
    argv = ["deduire", "--data-dir", str(data), "--domaine", "code", "--directive", str(directive)]
    assert main(argv) == 2  # gate : interdite par défaut
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
                "deduction": "enabled",
            }
        ),
        encoding="utf-8",
    )
    assert main(argv) == 0
    sorties = json.loads(capsys.readouterr().out)
    assert sorties["proposees"] == 1 and sorties["consignees"] == 1
    assert main(argv) == 0  # idempotent : déjà présente
    assert json.loads(capsys.readouterr().out)["consignees"] == 0
