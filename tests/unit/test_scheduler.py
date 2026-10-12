# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.5 — scheduler : ordre, séquentiel, anti-famine, budgets, no-op."""

from __future__ import annotations

import threading
import time

from evidra.kernel.contracts import Cost, Status, ToolResult, Verb
from evidra.kernel.scheduler import Budgets, Priorite, Scheduler


def _recu(marque: str, journal: list[str]) -> ToolResult:
    journal.append(marque)
    return ToolResult(status=Status.OK, payload={"marque": marque})


def _toujours() -> bool:
    return True


def test_ordre_strict_des_priorites():
    journal: list[str] = []
    ordonnanceur = Scheduler()
    for niveau in (Priorite.P3, Priorite.P1, Priorite.P6, Priorite.P2):
        ordonnanceur.enregistrer(niveau, _toujours, lambda n=niveau: _recu(n.name, journal))
    rapport = ordonnanceur.tour()
    assert [r.niveau for r in rapport.recus] == [
        Priorite.P1,
        Priorite.P2,
        Priorite.P3,
        Priorite.P6,
    ]
    assert journal == ["P1", "P2", "P3", "P6"]


def test_deux_niveaux_sequentiels_dans_l_ordre():
    journal: list[str] = []
    ordonnanceur = Scheduler()
    ordonnanceur.enregistrer(Priorite.P4, _toujours, lambda: _recu("P4", journal))
    ordonnanceur.enregistrer(Priorite.P2, _toujours, lambda: _recu("P2", journal))
    rapport = ordonnanceur.tour()
    assert [r.niveau for r in rapport.recus] == [Priorite.P2, Priorite.P4]
    assert journal == ["P2", "P4"]


def test_antifamine_p4_sature_n_affame_pas_p5():
    journal: list[str] = []
    ordonnanceur = Scheduler(Budgets(max_tool_calls=4, reserve_fond=2))
    for niveau in Priorite:
        ordonnanceur.enregistrer(niveau, _toujours, lambda n=niveau: _recu(n.name, journal))
    rapport = ordonnanceur.tour()
    niveaux = [r.niveau for r in rapport.recus]
    assert Priorite.P4 in niveaux and Priorite.P5 in niveaux
    assert niveaux == sorted(niveaux)


def test_antifamine_fond_garanti_sous_chauffe_haute():
    journal: list[str] = []
    ordonnanceur = Scheduler(Budgets(max_tool_calls=4, reserve_fond=3))
    for niveau in Priorite:
        ordonnanceur.enregistrer(niveau, _toujours, lambda n=niveau: _recu(n.name, journal))
    rapport = ordonnanceur.tour()
    niveaux = [r.niveau for r in rapport.recus]
    assert niveaux[0] is Priorite.P1
    assert niveaux[1:] == [Priorite.P4, Priorite.P5, Priorite.P6]
    assert any(b.startswith("budget:") for b in rapport.budgets_depasse)


def test_depassement_budget_trace():
    ordonnanceur = Scheduler(Budgets(max_tool_calls=1))
    ordonnanceur.enregistrer(Priorite.P1, _toujours, lambda: _recu("P1", []))
    ordonnanceur.enregistrer(Priorite.P2, _toujours, lambda: _recu("P2", []))
    rapport = ordonnanceur.tour()
    assert len(rapport.recus) == 1
    assert "budget:max_tool_calls" in rapport.budgets_depasse


def test_cycle_noop_rapide():
    ordonnanceur = Scheduler()
    debut = time.perf_counter()
    rapport = ordonnanceur.tour()
    duree_ms = (time.perf_counter() - debut) * 1000.0
    assert rapport.recus == ()
    assert duree_ms < 10.0  # SLO P2 de l'étude


def test_evenement_future_resolue():
    ordonnanceur = Scheduler()
    futur = ordonnanceur.deposer(Priorite.P2, lambda: _recu("push", []))
    rapport = ordonnanceur.tour()
    assert [r.niveau for r in rapport.recus] == [Priorite.P2]
    assert futur.done() and futur.result().payload == {"marque": "push"}


def test_evenement_skipe_par_budget_resout_degrade():
    ordonnanceur = Scheduler(Budgets(max_tool_calls=0))
    futur = ordonnanceur.deposer(Priorite.P2, lambda: _recu("jamais", []))
    rapport = ordonnanceur.tour()
    assert rapport.recus == ()
    assert "budget:max_tool_calls" in rapport.budgets_depasse
    assert futur.done()
    assert futur.result().status is Status.DEGRADE


def test_effet_qui_leve_devient_failed():
    def boom() -> ToolResult:
        raise RuntimeError("panne")

    ordonnanceur = Scheduler()
    ordonnanceur.enregistrer(Priorite.P1, _toujours, boom)
    ordonnanceur.enregistrer(Priorite.P2, _toujours, lambda: _recu("P2", []))
    rapport = ordonnanceur.tour()
    assert rapport.recus[0].resultat.status is Status.FAILED
    assert rapport.recus[1].resultat.status is Status.OK  # l'ordonnanceur survit


def test_quota_ingest_et_poids_wal():
    journal: list[str] = []
    ordonnanceur = Scheduler(Budgets(max_ingest_per_cycle=1, max_wal_bytes=10))
    ordonnanceur.enregistrer(
        Priorite.P4, _toujours, lambda: _recu("i1", journal), verbe=Verb.INGEST
    )
    ordonnanceur.enregistrer(
        Priorite.P5, _toujours, lambda: _recu("i2", journal), verbe=Verb.INGEST
    )
    ordonnanceur.enregistrer(Priorite.P6, _toujours, lambda: _recu("gros", journal), wal_bytes=100)
    rapport = ordonnanceur.tour()
    assert journal == ["i1"]
    assert "budget:max_ingest_per_cycle" in rapport.budgets_depasse
    assert "budget:max_wal_bytes" in rapport.budgets_depasse


def test_boucler_s_arrete_sur_signal():
    ordonnanceur = Scheduler()
    arret = threading.Event()
    arret.set()
    fil = threading.Thread(target=ordonnanceur.boucler, args=(arret,))
    fil.start()
    fil.join(timeout=5.0)
    assert not fil.is_alive()
    assert ordonnanceur.tick == 0


def test_cout_recu():
    def couteux() -> ToolResult:
        return ToolResult(status=Status.OK, payload={}, cost=Cost(ms=2.0, calls=1))

    ordonnanceur = Scheduler()
    ordonnanceur.enregistrer(Priorite.P6, _toujours, couteux)
    (recu,) = ordonnanceur.tour().recus
    assert recu.resultat.cost == Cost(ms=2.0, calls=1)
