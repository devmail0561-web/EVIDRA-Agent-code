# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.7 — rapport de chargement par stream (consommé en T4.5)."""

from __future__ import annotations

from pathlib import Path

from evidra.memory.snapshot import charger, compacter, ecrire_snapshot, sous_dossier
from evidra.memory.wal import WAL


def _appliquer(etat: dict, enr) -> None:
    etat[enr.cle] = dict(enr.donnees)


def test_rapport_chargement_snapshot_et_rejeu(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    with WAL(dossier / "wal.jsonl") as journal:
        journal.append("add", "a", {"n": 1})
        journal.sync()
        charge = charger(dossier, journal, appliquer=_appliquer, stream="domains/code")
        compacter(dossier, journal, charge.etat, charge.last_seq)
    with WAL(dossier / "wal.jsonl", seq_depart=1) as journal:
        journal.append("add", "b", {"n": 2})
        journal.sync()
        recharge = charger(dossier, journal, appliquer=_appliquer, stream="domains/code")
    assert recharge.rapport is not None
    rapport = recharge.rapport.en_dict()
    assert rapport["stream"] == "domains/code"
    assert rapport["snapshot_loaded"] is True
    assert rapport["source"] == "snapshot"
    assert rapport["replayed"] == 1
    assert rapport["skipped"] == 0 and rapport["crc_failed"] == 0 and rapport["seq_gaps"] == 0
    assert rapport["duration_ms"] >= 0.0


def test_rapport_chargement_vide(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    ecrire_snapshot(dossier, {}, 0)
    (dossier / "snapshot.json").write_bytes("cassé{".encode())
    with WAL(dossier / "wal.jsonl") as journal:
        charge = charger(dossier, journal, appliquer=_appliquer, stream="registry/tasks")
    assert charge.rapport is not None
    assert charge.rapport.snapshot_loaded is False
    assert charge.rapport.source == "vide"
