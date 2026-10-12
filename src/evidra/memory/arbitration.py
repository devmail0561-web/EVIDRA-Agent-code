# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Arbitrage des conflits (T6.4) : score composite + quorum, pur.

`score = conf_extraction × reliability(source) × norm_conf(n) × freshness`
(§6.9) ; `norm_conf(n) = log2(1+n) / log2(1+Nmax)` plafonné à 1.
Règle : `ratio > seuil ⇒ l'arête l'emporte, sinon EN RÉVISION`.
Par défaut strict : seuil = `seuil_revision` (3.0, amendement — EN RÉVISION
sous 3.0) ; calibration T10.4 pourra descendre à `seuil_quorum` (2.0).

Garde anti-double-pondération : `reliability` est la fiabilité SOURCE
(registre T6.3), jamais une confiance moteur qui l'intègre déjà — la
fonction multiplie exactement ses 4 arguments, test dédié.
Premier rapporteur isolé contre consensus ⇒ EN RÉVISION (gel du bonus
`novelty`, jamais pénalité de fiabilité). Variante noisy-OR fournie
pour comparaison T10.4 — NON FIGÉE, `produit` par défaut documenté.
Résolution : MAINTENUE (gagnante revue) ou INVALIDEE (tombstone motivé,
jamais silencieuse) ; application = appelant (WAL + `changer_statut`).
"""

from __future__ import annotations

import math

FORMULE_DEFAUT = "produit"


def norm_conf(n: int, nmax: float | int) -> float:
    """Bonus logarithmique normalisé ∈ [0,1] (`nmax` en directive)."""
    if nmax <= 0:
        raise ValueError(f"nmax invalide : {nmax!r}")
    if n <= 0:
        return 0.0
    return min(1.0, math.log2(1 + n) / math.log2(1 + nmax))


def score_produit(
    conf_extraction: float,
    fiabilite_source: float,
    n_confirmations: int,
    fraicheur: float,
    *,
    nmax: float | int,
) -> float:
    """Produit exact des 4 facteurs (garde anti-double-pondération : rien d'autre)."""
    return conf_extraction * fiabilite_source * norm_conf(n_confirmations, nmax) * fraicheur


def score_noisy_or(conf_extraction: float, n_confirmations: int, *, nmax: float | int) -> float:
    """Candidat T10.4 (NON FIGÉ) : `1 − (1−c)^(1+log2(1+n)/log2(1+nmax))`.

    Les confirmations réduisent l'incertitude sans fiabilité source ;
    comparatif chiffré sur corpus avant de figer (§16.2 de l'étude).
    """
    poids = norm_conf(n_confirmations, nmax)
    return float(1.0 - (1.0 - conf_extraction) ** (1.0 + poids))


def arbitrer(score_a: float, score_b: float, *, seuil: float) -> tuple[str, float]:
    """`(verdict, ratio)` : `"A"`, `"B"` si ratio > seuil, sinon `"revision"`.

    `ratio = max/min` ; `min == 0` : gagnant si l'autre > 0, sinon révision.
    Jamais levée (I12) : entrées non numériques ⇒ révision motivée ratio 1.0.
    """
    try:
        a, b = float(score_a), float(score_b)
    except (TypeError, ValueError):
        return "revision", 1.0
    if a < 0 or b < 0:
        return "revision", 1.0
    if a == b:
        return "revision", 1.0
    gagnant, fort, faible = ("A", a, b) if a > b else ("B", b, a)
    if faible <= 0.0:
        return (gagnant, float("inf")) if fort > 0.0 else ("revision", 1.0)
    ratio = fort / faible
    return (gagnant, ratio) if ratio > seuil else ("revision", ratio)


def proteger_nouveaute(n_gagnant: int, n_perdant: int) -> bool:
    """Premier rapporteur isolé contre consensus ⇒ EN RÉVISION (gel)."""
    return n_perdant <= 1 < n_gagnant


def decider(
    score_a: float, n_a: int, score_b: float, n_b: int, *, seuil: float
) -> tuple[str, float, str]:
    """`(verdict, ratio, motif)` : quorum + gel nouveauté (pur, testé §6.9)."""
    verdict, ratio = arbitrer(score_a, score_b, seuil=seuil)
    if verdict in ("A", "B"):
        n_gagnant, n_perdant = (n_a, n_b) if verdict == "A" else (n_b, n_a)
        if proteger_nouveaute(n_gagnant, n_perdant):
            return "revision", ratio, "nouveauté isolée contre consensus : EN RÉVISION (gel)"
        return verdict, ratio, f"ratio {ratio:.2f} > seuil {seuil}"
    return "revision", ratio, f"ratio {ratio:.2f} ≤ seuil {seuil}"
