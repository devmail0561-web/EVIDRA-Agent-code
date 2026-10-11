# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.2 — snapshot/compaction : repli, fautes, seuil, confinement (ADR-0011)."""

from __future__ import annotations

from pathlib import Path

import pytest

from evidra.memory.snapshot import (
    NOM_SNAPSHOT,
    NOM_WAL,
    PanneSimulee,
    charger,
    compacter,
    ecrire_snapshot,
    sous_dossier,
)
from evidra.memory.wal import WAL, Enregistrement


def appliquer(etat: dict, enr: Enregistrement) -> None:
    if enr.op == "tombstone":
        etat.pop(enr.cle, None)
    elif enr.op == "add":
        etat[enr.cle] = dict(enr.donnees)


def _etat_de_base(dossier: Path) -> tuple[dict, int]:
    with WAL(dossier / NOM_WAL) as journal:
        journal.append("add", "a", {"n": 1})
        journal.append("add", "b", {"n": 2})
        journal.append("tombstone", "a", {})
        journal.sync()
        rapport = compacter(dossier, journal, {"b": {"n": 2}}, 3)
    assert rapport.effectuee is True
    return {"b": {"n": 2}}, 3


def test_compacter_puis_charger_identique(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    _etat_de_base(dossier)
    assert (dossier / NOM_SNAPSHOT).exists()
    assert (dossier / NOM_WAL).stat().st_size == 0
    with WAL(dossier / NOM_WAL, seq_depart=3) as journal:
        journal.append("add", "c", {"n": 3})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
    assert charge.etat == {"b": {"n": 2}, "c": {"n": 3}}
    assert charge.last_seq == 4 and charge.source == "snapshot"
    with WAL(dossier / NOM_WAL, seq_depart=charge.last_seq) as journal:
        assert journal.append("add", "d", {}) == 5  # seq continue après chargement


def test_deuxieme_compaction_garde_prev(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    _etat_de_base(dossier)
    with WAL(dossier / NOM_WAL, seq_depart=3) as journal:
        journal.append("add", "c", {"n": 3})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
        compacter(dossier, journal, charge.etat, charge.last_seq)
    assert (dossier / "snapshot.json.prev").exists()


@pytest.mark.parametrize("etape", ["tmp", "prev", "rename", "troncation"])
def test_panne_a_chaque_etape_etat_recharge_identique(tmp_path: Path, etape: str) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    _etat_de_base(dossier)
    with WAL(dossier / NOM_WAL, seq_depart=3) as journal:
        journal.append("add", "c", {"n": 3})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
        with pytest.raises(PanneSimulee):
            compacter(dossier, journal, charge.etat, charge.last_seq, panne_apres=etape)
    with WAL(dossier / NOM_WAL) as journal:
        recharge = charger(dossier, journal, appliquer=appliquer)
    assert recharge.etat == {"b": {"n": 2}, "c": {"n": 3}}
    assert recharge.last_seq == 4


def test_compaction_reprise_apres_panne_tmp(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    _etat_de_base(dossier)
    with WAL(dossier / NOM_WAL, seq_depart=3) as journal:
        journal.append("add", "c", {"n": 3})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
        with pytest.raises(PanneSimulee):
            compacter(dossier, journal, charge.etat, charge.last_seq, panne_apres="tmp")
        rapport = compacter(dossier, journal, charge.etat, charge.last_seq)
    assert rapport.effectuee is True


def test_snapshot_corrompu_repli_prev(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    ecrire_snapshot(dossier, {"a": {"n": 1}}, 1)
    with WAL(dossier / NOM_WAL, seq_depart=1) as journal:
        journal.append("add", "b", {"n": 2})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
        assert charge.etat == {"a": {"n": 1}, "b": {"n": 2}}
        ecrire_snapshot(dossier, charge.etat, charge.last_seq)  # snap v2, prev v1, WAL intact
    (dossier / NOM_SNAPSHOT).write_bytes(b"corrompu{")
    with WAL(dossier / NOM_WAL, seq_depart=2) as journal:
        journal.append("add", "c", {"n": 3})
        journal.sync()
        recharge = charger(dossier, journal, appliquer=appliquer)
    assert recharge.source == "prev"
    assert recharge.avertissements != ()
    assert recharge.etat == {"a": {"n": 1}, "b": {"n": 2}, "c": {"n": 3}}
    # Limite documentée : si le WAL a été tronqué après compaction, l'intervalle
    # prev→snapshot corrompu n'est plus rejouable (cas couvert : écriture déchirée,
    # où le WAL intact permet la récupération complète — cf. tests PanneSimulee).


def test_version_inconnue_demarrage_vide(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    ecrire_snapshot(dossier, {"a": {}}, 1, version=99)
    with WAL(dossier / NOM_WAL) as journal:
        charge = charger(dossier, journal, appliquer=appliquer)
    assert charge.source == "vide" and charge.etat == {}
    assert charge.avertissements != ()


def test_tombstone_sans_snapshot_force(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    with WAL(dossier / NOM_WAL) as journal:
        journal.append("add", "a", {"n": 1})
        journal.append("tombstone", "a", {})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
    assert charge.etat == {} and charge.source == "vide" and charge.last_seq == 2


def test_seuil_octets(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    with WAL(dossier / NOM_WAL) as journal:
        journal.append("add", "a", {})
        journal.sync()
        petit = compacter(dossier, journal, {"a": {}}, 1, seuil_octets=10**9)
        assert petit.effectuee is False
        assert (dossier / NOM_WAL).stat().st_size > 0
        grand = compacter(dossier, journal, {"a": {}}, 1, seuil_octets=1)
        assert grand.effectuee is True
        assert (dossier / NOM_WAL).stat().st_size == 0


def test_etape_inconnue_refusee(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    with WAL(dossier / NOM_WAL) as journal, pytest.raises(ValueError):
        compacter(dossier, journal, {}, 0, panne_apres="jamais")


def test_rien_hors_du_dossier_de_stream(tmp_path: Path) -> None:
    dossier = sous_dossier(tmp_path, "domaine")
    dossier.mkdir(parents=True)
    _etat_de_base(dossier)
    with WAL(dossier / NOM_WAL, seq_depart=3) as journal:
        journal.append("add", "c", {})
        journal.sync()
        charge = charger(dossier, journal, appliquer=appliquer)
        compacter(dossier, journal, charge.etat, charge.last_seq)
    dehors = [
        p for p in tmp_path.rglob("*") if p.is_file() and dossier not in p.parents and p != dossier
    ]
    assert dehors == []
    assert (dossier / "sa.lock").exists()  # verrou dans le dossier de stream…
    assert not (tmp_path / "sa.lock").exists()  # …jamais à côté des sources
    assert not (dossier.parent / NOM_SNAPSHOT).exists()


def test_sous_dossier_refuse_evasion(tmp_path: Path) -> None:
    assert sous_dossier(tmp_path, "domaine", "sous").parent.name == "domaine"
    for interdit in ("..", ".", "", "/absolu", "a/b", "a\\b"):
        with pytest.raises(ValueError):
            sous_dossier(tmp_path, interdit)
    with pytest.raises(ValueError):
        sous_dossier(tmp_path)
