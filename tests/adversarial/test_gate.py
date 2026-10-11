# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.4 — suite adversariale initiale de la porte `can()`."""

from __future__ import annotations

from typing import Any

from evidra.kernel.contracts import Status, Verb
from evidra.kernel.gate import Policy, Rule, can, refuse


def _policy(**kwargs: Any) -> Policy:
    return Policy(**kwargs)


def test_defaut_read_autorise_autres_refuses():
    vide = _policy()
    assert can(vide, "nimporte-quoi", Verb.READ, "nimporte-ou")
    for verbe in (Verb.INGEST, Verb.MODIFY, Verb.DELETE, Verb.ALERT, Verb.EGRESS):
        decision = can(vide, "nimporte-quoi", verbe, "nimporte-ou", motif="m")
        assert not decision
        assert "aucune permission" in decision.motif


def test_verbe_inconnu_refuse_sans_lever():
    decision = can(_policy(), "outil", "boum", "scope")  # type: ignore[arg-type]
    assert not decision
    assert "verbe inconnu" in decision.motif


def test_scope_vide_refuse():
    assert not can(_policy(), "outil", Verb.READ, "")
    assert "vide" in can(_policy(), "outil", Verb.READ, "").motif


def test_outil_vide_refuse():
    assert not can(_policy(), "", Verb.READ, "scope")


def test_pas_d_heritage_par_elargissement():
    policy = _policy(allowed=frozenset({Rule("outil", Verb.INGEST, "code")}))
    assert can(policy, "outil", Verb.INGEST, "code", motif="m")
    elargi = can(policy, "outil", Verb.INGEST, "code/sous", motif="m")
    assert not elargi  # le périmètre large n'hérite pas de l'étroit
    global_policy = _policy(allowed=frozenset({Rule("*", Verb.INGEST, "*")}))
    assert can(global_policy, "outil", Verb.INGEST, "code", motif="m")


def test_forbidden_exact_gagne_contre_defaut_read():
    policy = _policy(forbidden=frozenset({Rule("outil", Verb.READ, "code")}))
    assert not can(policy, "outil", Verb.READ, "code")
    assert can(policy, "outil", Verb.READ, "autre")  # exact seul, pas de préfixe


def test_forbidden_prioritaire_sur_allowed():
    regle = Rule("outil", Verb.INGEST, "code")
    policy = _policy(allowed=frozenset({regle}), forbidden=frozenset({regle}))
    decision = can(policy, "outil", Verb.INGEST, "code")
    assert not decision
    assert "interdit" in decision.motif


def test_delete_exige_un_motif():
    regle = Rule("outil", Verb.DELETE, "code")
    policy = _policy(allowed=frozenset({regle}))
    assert not can(policy, "outil", Verb.DELETE, "code")
    assert can(policy, "outil", Verb.DELETE, "code", motif="source invalide")


def test_refus_devient_recu_trace():
    recu = refuse("outil", Verb.DELETE, "code", "sans motif")
    assert recu.status is Status.REFUSED
    assert recu.payload["motif"] == "sans motif"
    assert recu.payload["outil"] == "outil"
    assert recu.trace_ref is None
