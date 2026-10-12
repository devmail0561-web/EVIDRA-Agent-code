# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T7.3 — lacunes : formulation, priorité, tâches P4, CLI gracieux."""

from __future__ import annotations

import json
from pathlib import Path

from evidra.boot.demarrage import demarrer
from evidra.memory.registres import Registres
from evidra.memory.store import Magasin
from evidra.monitor.lacunes import fiche_tache, formuler, planifier


def test_formuler_question() -> None:
    question = formuler(["a", "b", "c"], ["x"])
    assert question.question.startswith("quelles sources acquérir pour compléter ")
    assert question.prioritaire is True
    assert formuler(["a"], []).prioritaire is False


def test_planifier_priorite_stable() -> None:
    questions = planifier(
        [["b", "c"], ["a", "b"], []],
        {"a>b": ["x"]},
    )
    assert [list(q.chaine) for q in questions] == [["a", "b"], ["b", "c"]]
    assert all(q.prioritaire for q in questions[:1])


def test_fiche_tache_p4_budgetee() -> None:
    fiche = fiche_tache(formuler(["a", "b"], ["x"]), budget=10.0, deadline="2030-01-01", rang=0)
    assert fiche["type"] == "fetch" and fiche["budget"] == 10.0
    assert "quelles sources" in fiche["question"] and fiche["rang"] == 0


def test_creer_tache_extras_compatibles(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.creer_tache("t1", "fetch", 10.0, "2030-01-01", extras={"question": "q?"})
        fiche = registres.tache("t1")
        assert fiche is not None and fiche["question"] == "q?"
        assert fiche["etat"] == "pending" and fiche["type"] == "fetch"
        registres.creer_tache("t2", "ingest", 5.0, "2030-01-01")
        assert registres.tache("t2") is not None and "question" not in registres.tache("t2")


def test_cli_lacunes_sans_binaire_gracieux(tmp_path: Path, capsys) -> None:
    from evidra.cli import main

    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(
        json.dumps(
            {
                "agent_id": "t",
                "domain": "code",
                "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "*"}]},
                "monitoring": {"watch_gaps_in_chains": [["a", "b"]]},
            }
        ),
        encoding="utf-8",
    )
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.magasin is not None
    rapport.magasin.close()
    argv = [
        "lacunes",
        "--data-dir",
        str(data),
        "--domaine",
        "code",
        "--directive",
        str(directive),
        "--deadline",
        "2030-01-01T00:00:00+00:00",
    ]
    assert main(argv) == 0
    sorties = json.loads(capsys.readouterr().out)
    assert sorties["questions"] == 1 and sorties["taches_creees"] == 0
