# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Générateur CTI synthétique partagé (T2.8) : graphes 10k/100k/500k arêtes."""

from __future__ import annotations

import random

from evidra.memory.index import Index

CONCEPTS = [f"concept-{i:04d}" for i in range(5000)]
VARIANTES = ["auth", "login", "panne", "cve", "patch", "serveur"]
RELATIONS = ["causes", "prevents"]


def construire(n: int, graine: int = 7) -> Index:
    """n arêtes déterministes (hubs + 5 % de variantes lexicales)."""
    hasard = random.Random(graine)
    index = Index()
    for i in range(n):
        src = hasard.choice(CONCEPTS)
        if hasard.random() < 0.05:
            src = f"{src} {hasard.choice(VARIANTES)}"
        index.ajouter(
            f"e{i:06d}", src, hasard.choice(CONCEPTS), hasard.choice(RELATIONS), hasard.random()
        )
    return index


def requetes(pas: int = 25) -> list[str]:
    """200 requêtes réparties sur les concepts."""
    return [f"concept-{i:04d}" for i in range(0, 5000, pas)]
