# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T7.1 — conditions pures : déclenchement, sévérités, anti-ReDoS."""

from __future__ import annotations

from evidra.monitor.conditions import (
    Condition,
    conflit_non_resolu,
    haute_confiance_invalidee,
    motif_dangereux,
    nouvelle_relation,
    source_suspecte,
)


def test_nouvelle_relation_motif() -> None:
    cond = nouvelle_relation(("code", "ransomware x", "cause", "panne"), ["ransomware"])
    assert isinstance(cond, Condition)
    assert cond is not None and cond.severite == "avertissement"
    assert cond.cle.startswith("nouvelle_relation:ransomware:")
    assert nouvelle_relation(("code", "soleil", "cause", "pluie"), ["ransomware"]) is None


def test_motif_dangereux_rejete() -> None:
    assert motif_dangereux("(a+)+") is True
    assert motif_dangereux("([a-z]+)+$") is True
    assert motif_dangereux("x" * 201) is True
    assert motif_dangereux("[invalid") is True
    assert motif_dangereux("CVE-2024-.*") is False
    assert motif_dangereux("ransomware|phishing") is False
    assert nouvelle_relation(("code", "a", "cause", "b"), ["(a+)+"]) is None


def test_haute_confiance_invalidee() -> None:
    triplet = ("code", "a", "cause", "b")
    cond = haute_confiance_invalidee(triplet, "invalidee", 0.9, seuil=0.8)
    assert cond is not None and cond.severite == "critique"
    assert haute_confiance_invalidee(triplet, "invalidee", 0.5, seuil=0.8) is None
    assert haute_confiance_invalidee(triplet, "confirmee", 0.9, seuil=0.8) is None


def test_conflit_non_resolu() -> None:
    triplet = ("code", "a", "cause", "b")
    assert conflit_non_resolu(triplet, "en_revision") is not None
    assert conflit_non_resolu(triplet, "confirmee") is None


def test_source_suspecte() -> None:
    assert source_suspecte("doc://x", "suspect") is not None
    assert source_suspecte("doc://x", "trusted") is None
    assert source_suspecte("doc://x", "monitored") is None
