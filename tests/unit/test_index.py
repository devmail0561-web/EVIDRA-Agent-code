# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.5 — index : propriété d'équivalence avec le scan linéaire naïf."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from evidra.memory.envelope import normaliser_label
from evidra.memory.index import Index

MOTS = st.sampled_from(["auth", "login", "ransomware", "cve", "patch", "serveur", "dns", "vpn"])
LABEL = st.lists(MOTS, min_size=1, max_size=3).map(" ".join)
RELATIONS = st.sampled_from(["causes", "prevents", "enables"])
ARETE = st.tuples(LABEL, LABEL, RELATIONS, st.floats(min_value=0.0, max_value=1.0))


def _scan_causes(aretes: dict[str, tuple], label: str) -> set[str]:
    cible = normaliser_label(label)
    exacts = {i for i, (_, dst, _, _) in aretes.items() if normaliser_label(dst) == cible}
    if exacts:
        return exacts
    tokens = set(cible.split())
    trouves = set()
    for i, (src, dst, _, _) in aretes.items():
        if tokens & (set(normaliser_label(src).split()) | set(normaliser_label(dst).split())):
            trouves.add(i)
    return trouves


def _scan_effets(aretes: dict[str, tuple], label: str) -> set[str]:
    cible = normaliser_label(label)
    exacts = {i for i, (src, _, _, _) in aretes.items() if normaliser_label(src) == cible}
    if exacts:
        return exacts
    tokens = set(cible.split())
    trouves = set()
    for i, (src, dst, _, _) in aretes.items():
        if tokens & (set(normaliser_label(src).split()) | set(normaliser_label(dst).split())):
            trouves.add(i)
    return trouves


@given(
    st.dictionaries(st.text(min_size=1, max_size=6), ARETE, max_size=40),
    st.lists(LABEL, max_size=5),
)
@settings(max_examples=30)
def test_propriete_index_egale_scan(aretes: dict[str, tuple], requetes: list[str]) -> None:
    index = Index()
    index.reconstruire(aretes)
    for requete in requetes:
        assert set(index.causes(requete)) == _scan_causes(aretes, requete)
        assert set(index.effets(requete)) == _scan_effets(aretes, requete)


@given(st.dictionaries(st.text(min_size=1, max_size=6), ARETE, max_size=40))
@settings(max_examples=30)
def test_propriete_retrait_tombstone(aretes: dict[str, tuple]) -> None:
    vives = dict(aretes)
    index = Index()
    index.reconstruire(aretes)
    for ident in list(aretes)[: len(aretes) // 2]:
        index.retirer(ident)
        del vives[ident]
    index.retirer("inexistant")  # retrait idempotent, sans effet
    for requete in ("auth", "ransomware patch", "inconnu xyz"):
        assert set(index.causes(requete)) == _scan_causes(vives, requete)
        assert set(index.effets(requete)) == _scan_effets(vives, requete)
    assert len(index) == len(vives)


def test_tiers_provisoires() -> None:
    index = Index()
    index.ajouter("h", "a", "b", "causes", 0.90)
    index.ajouter("m", "a", "b", "causes", 0.70)
    index.ajouter("l", "a", "b", "causes", 0.10)
    assert set(index.par_tier("high")) == {"h"}
    assert set(index.par_tier("medium")) == {"m"}
    assert set(index.par_tier("low")) == {"l"}
    assert set(index.par_relation("causes")) == {"h", "m", "l"}
    assert index.stats()["aretes"] == 3
