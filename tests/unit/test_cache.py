# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T5.6 — cache : propriété avec≡sans, compteurs, époques, LRU, tombstones."""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evidra.memory.cache import CacheResultats
from evidra.memory.envelope import CirCore, Provenance
from evidra.memory.memoire import Memoire


def _noyau(src: str = "A", dst: str = "B", ref: str = "r") -> CirCore:
    return CirCore(
        source=src,
        target=dst,
        relation="cause",
        confidence=0.8,
        provenance=Provenance(
            ref=ref, span="synthetic", extraction_method="m", model_version="v", extracted_at="t"
        ),
    )


LABELS = st.sampled_from(["alpha", "beta", "gamma", "delta"])
RELS = st.sampled_from(["cause", "prevent"])
OP_ADD = st.tuples(st.just("add"), LABELS, LABELS, RELS, st.integers(min_value=0, max_value=5))
OP_RETIRE = st.tuples(st.just("retire"), LABELS, LABELS, RELS)
OP_QUERY = st.tuples(st.just("query"), st.sampled_from(["causes", "effets"]), LABELS)
OPS = st.lists(st.one_of(OP_ADD, OP_RETIRE, OP_QUERY), max_size=40)


def _direct(memo: Memoire, sens: str, label: str) -> tuple[tuple[str, ...], str]:
    index = memo.index
    exact = index.entrants(label) if sens == "causes" else index.sortants(label)
    direct = index.causes(label) if sens == "causes" else index.effets(label)
    if direct:
        return direct, ("exacte" if exact else "tokens")
    frais = index.par_sous_chaine(label)
    return (frais, "sous-chaine") if frais else ((), "vide")


@given(OPS)
@settings(max_examples=40)
def test_propriete_cache_egale_sans_cache(ops: list) -> None:
    memo = Memoire("test")
    for op in ops:
        if op[0] == "add":
            _, src, dst, rel, k = op
            memo.observer(
                _noyau(src, dst, f"doc://{k}"), channel="test", fiabilite=0.5, horodatage="t"
            )
        elif op[0] == "retire":
            _, src, dst, rel = op
            memo.retirer(("test", src.lower(), rel, dst.lower()))
        else:
            _, sens, label = op
            ids, resolution, _touche = memo.rechercher(sens, label)
            attendus, res_attendue = _direct(memo, sens, label)
            assert set(ids) == set(attendus) and resolution == res_attendue


def test_compteurs_hit_miss() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(), channel="t", fiabilite=0.5, horodatage="t")
    assert memo.rechercher("causes", "B")[2] is False  # miss
    assert memo.rechercher("causes", "B")[2] is True  # hit : servi sans recalcul
    assert memo.rechercher("causes", "B")[0] == memo.rechercher("causes", "B")[0]
    compteurs = memo.cache.compteurs()
    assert compteurs["hits"] >= 1 and compteurs["misses"] >= 1


def test_confirmation_n_invalide_pas() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(ref="r1"), channel="t", fiabilite=0.5, horodatage="t")
    memo.rechercher("causes", "B")
    hits_avant = memo.cache.compteurs()["hits"]
    memo.observer(
        _noyau(ref="r2"), channel="t", fiabilite=0.5, horodatage="t"
    )  # confirmation : mêmes ids
    ids, _, touche = memo.rechercher("causes", "B")
    assert touche is True and memo.cache.compteurs()["hits"] == hits_avant + 1
    assert len(ids) == 1


def test_tombstone_invalide() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(), channel="t", fiabilite=0.5, horodatage="t")
    assert memo.rechercher("causes", "B")[0] != ()
    assert memo.retirer(("code", "a", "cause", "b")) is True
    assert memo.retirer(("code", "a", "cause", "b")) is False
    ids, resolution, touche = memo.rechercher("causes", "B")
    assert touche is False and ids == () and resolution == "vide"
    assert memo.cache.compteurs()["invalidations"] >= 1


def test_epoques_separees() -> None:
    memo = Memoire("code")
    memo.observer(_noyau(), channel="t", fiabilite=0.5, horodatage="t")
    assert memo.rechercher("causes", "B", epoque=1)[2] is False
    assert memo.rechercher("causes", "B", epoque=1)[2] is True
    assert memo.rechercher("causes", "B", epoque=2)[2] is False  # autre époque : autre entrée
    assert (
        memo.rechercher("causes", "B", epoque=1)[0] == memo.rechercher("causes", "B", epoque=2)[0]
    )


def test_lru_borne() -> None:
    cache = CacheResultats(taille_max=3)
    for mot in ("a", "b", "c", "d", "e"):
        cache.ecrire(mot, "causes", (f"id-{mot}",))
    assert cache.compteurs()["taille"] == 3
    assert cache.lire("a", "causes") is None  # évincé (plus ancien)
    assert cache.lire("e", "causes") == ("id-e",)
    with pytest.raises(ValueError):
        CacheResultats(taille_max=0)
