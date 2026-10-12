# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.4 — boucle : ordre P2<P4, budget tracé, anti-famine, tiède, borner."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from evidra.boucle import Boucle, borner, outils_niveau
from evidra.directive.loader import charger
from evidra.directive.reload import Surveillant
from evidra.kernel.contracts import Status, ToolResult
from evidra.kernel.scheduler import Budgets, Priorite, Scheduler
from evidra.memory.registres import Registres
from evidra.memory.store import Magasin


def _ok(marque: str) -> ToolResult:
    return ToolResult(status=Status.OK, payload={"marque": marque})


def _montage(
    tmp_path: Path,
    directive: dict | None = None,
    outils: dict | None = None,
    budgets: Budgets | None = None,
) -> tuple[Boucle, Magasin, Registres, Scheduler]:
    magasin = Magasin(tmp_path / "data")
    registres = Registres(magasin)
    ordonnanceur = Scheduler(
        budgets if budgets is not None else Budgets(max_tool_calls=6, reserve_fond=1)
    )
    surveillant = None
    if directive is not None:
        chemin = tmp_path / "directive.json"
        chemin.write_text(json.dumps(directive), encoding="utf-8")
        surveillant = Surveillant(chemin, charger(chemin))
    boucle = Boucle(
        domaine="code",
        ordonnanceur=ordonnanceur,
        magasin=magasin,
        registres=registres,
        outils=outils if outils is not None else {},
        surveillant=surveillant,
        horloge=lambda: "2026-10-12T00:00:00+00:00",
    )
    return boucle, magasin, registres, ordonnanceur


def _directive(budgets: dict | None = None) -> dict:
    return {"agent_id": "t", "domain": "code", "budgets": budgets or {}}


def test_claim_p2_avant_donnees_p4(tmp_path: Path) -> None:
    journal: list[str] = []
    boucle, _mag, registres, ordonnanceur = _montage(
        tmp_path, _directive(), {"ingest": lambda: _ok("ingest")}
    )
    registres.creer_tache("d1", "ingest", 10.0, "2030-01-01T00:00:00+00:00")

    def _revendication() -> object:
        journal.append("P2")
        return _ok("claim")

    futur = ordonnanceur.deposer(Priorite.P2, _revendication)  # type: ignore[arg-type]
    rapport = boucle.tick()
    assert [r.niveau for r in rapport.recus] == [Priorite.P2, Priorite.P4]
    assert journal == ["P2"]
    assert futur.done()
    assert Priorite.P2 not in rapport.selection  # P2 venu d'un dépôt externe, pas de la politique
    assert Priorite.P4 in rapport.selection  # P4 vu via la tâche


def test_budget_degrade_trace(tmp_path: Path) -> None:
    boucle, _mag, registres, _ord = _montage(
        tmp_path,
        _directive({"max_tool_calls": 1}),
        {"ingest": lambda: _ok("i1"), "maintenance": lambda: _ok("m")},
    )
    registres.creer_tache("d1", "ingest", 10.0, "2030-01-01T00:00:00+00:00")
    registres.creer_tache("s1", "maintenance", 10.0, "2030-01-01T00:00:00+00:00")
    rapport = boucle.tick()
    assert len(rapport.recus) == 1
    assert "budget:max_tool_calls" in rapport.budgets_depasse


def test_pas_de_famine_p5_p6_sous_charge_p4(tmp_path: Path) -> None:
    def _fabrique(marque: str):
        return lambda: _ok(marque)

    outils = {
        "ingest": _fabrique("ingest"),
        "maintenance": _fabrique("maintenance"),
        "query_cycles": _fabrique("cycles"),
    }
    boucle, _mag, registres, _ord = _montage(
        tmp_path, _directive({"max_tool_calls": 6, "reserve_fond": 1}), outils
    )
    for i in range(3):
        registres.creer_tache(f"d{i}", "ingest", 10.0, "2030-01-01T00:00:00+00:00")
    registres.creer_tache("s1", "maintenance", 10.0, "2030-01-01T00:00:00+00:00")
    registres.creer_tache("f1", "query_cycles", 10.0, "2030-01-01T00:00:00+00:00")
    marques = []
    for _ in range(3):
        rapport = boucle.tick()
        marques.extend(r.resultat.payload.get("marque") for r in rapport.recus)
    assert "maintenance" in marques and "cycles" in marques


def test_tiede_change_budgets_et_hash_wal(tmp_path: Path) -> None:
    boucle, magasin, _reg, _ord = _montage(tmp_path, _directive({"max_tool_calls": 6}))
    premier = boucle.tick()
    assert premier.directive_changee is False
    (tmp_path / "directive.json").write_text(
        json.dumps(_directive({"max_tool_calls": 1})), encoding="utf-8"
    )
    second = boucle.tick()
    assert second.directive_changee is True
    trouves = [
        e
        for e in magasin.flux("domains/code").relire().valides
        if e.op == "receipt" and e.donnees.get("sorte") == "directive"
    ]
    assert len(trouves) == 1
    assert trouves[0].donnees["hash"] == boucle._hash_directive


def test_tick_noop_zero_ecriture(tmp_path: Path) -> None:
    boucle, magasin, _reg, _ord = _montage(tmp_path, _directive())
    rapport = boucle.tick()
    assert rapport.recus == () and rapport.selection == ()
    assert (tmp_path / "data" / "domains" / "code" / "wal.jsonl").exists() is False


def test_borner_degrade_par_score() -> None:
    retenus, tronque = borner([{"s": 1}, {"s": 5}, {"s": 3}], 2, score=lambda d: float(d["s"]))
    assert [d["s"] for d in retenus] == [5, 3] and tronque == 1
    with pytest.raises(ValueError):
        borner([], -1, score=lambda x: 0.0)


def test_outils_niveau_table() -> None:
    assert outils_niveau(Priorite.P1) == ("alert", "report")
    assert outils_niveau(Priorite.P6) == ("query_cycles", "query_gaps")


def test_boucler_arret_propre(tmp_path: Path) -> None:
    boucle, _mag, _reg, _ord = _montage(tmp_path)
    arret = threading.Event()
    arret.set()
    fil = threading.Thread(target=boucle.boucler, args=(arret,))
    fil.start()
    fil.join(timeout=5.0)
    assert not fil.is_alive()
