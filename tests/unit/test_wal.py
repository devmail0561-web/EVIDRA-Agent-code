# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.1 — WAL : append/rejeu, propriété hypothesis, tolérance aux fautes."""

from __future__ import annotations

import json
import tempfile
import zlib
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from evidra.memory.wal import WAL, WALError

CLES = st.text(min_size=1, max_size=12)
DONNEES = st.dictionaries(
    st.text(min_size=1, max_size=8), st.integers() | st.text(max_size=8), max_size=3
)
OPS = st.lists(
    st.tuples(st.sampled_from(["add", "confirm", "tombstone"]), CLES, DONNEES), max_size=30
)


@given(OPS)
@settings(max_examples=40)
def test_propriete_rejeu_egal_etat(ops: list[tuple[str, str, dict]]) -> None:
    with tempfile.TemporaryDirectory() as dossier:
        chemin = Path(dossier) / "wal.jsonl"
        with WAL(chemin) as journal:
            for op, cle, donnees in ops:
                journal.append(op, cle, donnees)
            journal.sync()
        with WAL(chemin) as relecture:
            rapport = relecture.relire()
    assert [(e.op, e.cle, dict(e.donnees)) for e in rapport.valides] == ops
    assert rapport.ignores == 0 and rapport.crc_invalides == 0 and rapport.trous_seq == 0
    assert [e.seq for e in rapport.valides] == list(range(1, len(ops) + 1))


def test_rejeu_tolere_lignes_invalides(tmp_path: Path) -> None:
    chemin = tmp_path / "wal.jsonl"
    with WAL(chemin) as journal:
        journal.append("add", "a", {"n": 1})
        journal.sync()
    with open(chemin, "ab") as flux:
        flux.write(b"pas du json\n")
        flux.write(
            b'{"seq": 99, "ts": "x", "op": "add", "key": "b", "data": {}, "crc": "00000000"}\n'
        )
        flux.write(b"\n")
    with WAL(chemin) as relecture:
        rapport = relecture.relire()
    assert len(rapport.valides) == 1 and rapport.valides[0].cle == "a"
    assert rapport.ignores == 3 and rapport.crc_invalides == 1


def test_ligne_finale_tronquee_ignoree(tmp_path: Path) -> None:
    chemin = tmp_path / "wal.jsonl"
    with WAL(chemin) as journal:
        journal.append("add", "a", {})
        journal.sync()
    with open(chemin, "ab") as flux:
        flux.write(b'{"seq": 2, "ts": "x", "op": "add", "key": "b", "data":')
    with WAL(chemin) as relecture:
        rapport = relecture.relire()
    assert len(rapport.valides) == 1
    assert rapport.tronquee_finale is True


def test_trou_seq_compte_sans_abort(tmp_path: Path) -> None:
    chemin = tmp_path / "wal.jsonl"
    with WAL(chemin) as journal:
        journal.append("add", "a", {})
        journal.sync()
    with open(chemin, "rb") as flux:
        lignes = flux.read().split(b"\n")
    valide = lignes[0].decode()
    objet = json.loads(valide)
    corps = {k: v for k, v in objet.items() if k != "crc"}

    def canonique(o: dict) -> bytes:
        return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()

    corps["seq"] = 5
    ligne = canonique({**corps, "crc": f"{zlib.crc32(canonique(corps)) & 0xFFFFFFFF:08x}"})
    with open(chemin, "ab") as flux:
        flux.write(ligne + b"\n")
    with WAL(chemin) as relecture:
        rapport = relecture.relire()
    assert len(rapport.valides) == 2
    assert rapport.trous_seq == 3


def test_deuxieme_instance_refusee(tmp_path: Path) -> None:
    with WAL(tmp_path / "wal.jsonl"), pytest.raises(WALError):
        WAL(tmp_path / "wal.jsonl")


def test_fsync_batch_configurable(tmp_path: Path) -> None:
    with WAL(tmp_path / "wal.jsonl", batch_lignes=3) as journal:
        for i in range(7):
            journal.append("add", f"k{i}", {})
    with WAL(tmp_path / "wal.jsonl") as relecture:
        assert len(relecture.relire().valides) == 7
