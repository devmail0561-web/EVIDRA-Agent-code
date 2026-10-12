# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T6.4 — arbitrage : exemple §6.9, quorum, anti-double-pondération, nouveauté."""

from __future__ import annotations

import math

import pytest

from evidra.memory.arbitration import (
    arbitrer,
    decider,
    norm_conf,
    proteger_nouveaute,
    score_noisy_or,
    score_produit,
)


def test_norm_conf_bornes() -> None:
    assert norm_conf(0, 50) == 0.0
    assert norm_conf(1, 50) == pytest.approx(math.log2(2) / math.log2(51))
    assert norm_conf(10**9, 50) == 1.0
    with pytest.raises(ValueError):
        norm_conf(3, 0)


def test_exemple_etude_6_9() -> None:
    score_a = score_produit(0.90, 0.85, 1, 1.0, nmax=50)
    score_b = score_produit(0.60, 0.72, 15, 1.0, nmax=50)
    assert score_a == pytest.approx(0.135, rel=0.02)
    assert score_b == pytest.approx(0.302, rel=0.02)
    # Quorum pur (sans gel nouveauté) : 2.24 > 2.0 ⇒ B, ≤ 3.0 ⇒ révision.
    assert arbitrer(score_a, score_b, seuil=2.0)[0] == "B"
    assert arbitrer(score_a, score_b, seuil=3.0)[0] == "revision"
    # Avec gel nouveauté (amendement) : 1 confirmation isolée ⇒ révision même à 2.0.
    verdict, ratio, _ = decider(score_a, 1, score_b, 15, seuil=2.0)
    assert verdict == "revision" and ratio == pytest.approx(2.24, rel=0.05)
    verdict3, _, motif3 = decider(score_a, 1, score_b, 15, seuil=3.0)
    assert verdict3 == "revision" and "≤ seuil" in motif3


def test_anti_double_ponderation() -> None:
    assert score_produit(0.9, 0.85, 1, 1.0, nmax=50) == 0.9 * 0.85 * norm_conf(1, 50) * 1.0


def test_nouveaute_isolee_revision() -> None:
    assert proteger_nouveaute(15, 1) is True
    assert proteger_nouveaute(15, 2) is False
    verdict, _, motif = decider(0.317, 15, 0.079, 1, seuil=2.0)
    assert verdict == "revision" and "nouveauté" in motif


def test_arbitrer_invalide_revision() -> None:
    assert arbitrer(-1.0, 0.5, seuil=2.0) == ("revision", 1.0)
    assert arbitrer(0.0, 0.0, seuil=2.0) == ("revision", 1.0)
    assert arbitrer(0.4, 0.0, seuil=2.0)[0] == "A"
    assert arbitrer("x", 0.5, seuil=2.0) == ("revision", 1.0)  # type: ignore[arg-type]


def test_noisy_or_candidat_non_fige() -> None:
    assert score_noisy_or(0.9, 0, nmax=50) == pytest.approx(0.9)
    assert score_noisy_or(0.9, 50, nmax=50) > score_noisy_or(0.9, 1, nmax=50)
