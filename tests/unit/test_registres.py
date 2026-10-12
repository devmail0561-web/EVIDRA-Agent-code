# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.6 — registres : roundtrip, expiration, curseurs, snapshot."""

from __future__ import annotations

from pathlib import Path

import pytest

from evidra.memory.registres import EtatTache, Registres
from evidra.memory.store import Magasin


def test_sources_roundtrip_et_tolerant(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.noter_source("https://exemple.test/rss", {"contribuees": 10})
        assert registres.source("https://exemple.test/rss") == {"contribuees": 10}
        assert registres.source("inconnue") is None
    with open(tmp_path / "registry" / "sources" / "wal.jsonl", "ab") as flux:
        flux.write(b"ligne pourrie\n")
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        assert registres.source("https://exemple.test/rss") == {"contribuees": 10}


def test_alias_par_domaine(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.definir_alias("code", "authentification", ["auth", "login"])
        assert registres.alias("code", "authentification") == ["auth", "login"]
        assert registres.alias("code", "inconnu") == []
        assert registres.alias("autre", "authentification") == []


def test_modeles_vides_puis_consignes(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        assert registres.modeles() == {}  # B2 non levé : rien de consommé
        registres.noter_modele(
            "sha256:abc",
            {"chemin": "/modeles/x.npz", "version_moteur": "4.0.0", "statut": "re-mesure-attendue"},
        )
        assert list(registres.modeles()) == ["sha256:abc"]


def test_taches_cycle_de_vie(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.creer_tache("t1", "ingest", 100.0, "2030-01-01T00:00:00+00:00")
        assert registres.tache("t1")["etat"] == EtatTache.ATTENTE.value
        registres.passer_etat("t1", EtatTache.COURS)
        registres.passer_etat("t1", EtatTache.TERMINEE)
        assert registres.tache("t1")["etat"] == EtatTache.TERMINEE.value


def test_expiration_abandon_motive_non_supprime(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.creer_tache("vieille", "ingest", 10.0, "2020-01-01T00:00:00+00:00")
        registres.creer_tache("future", "ingest", 10.0, "2030-01-01T00:00:00+00:00")
        abandonnees = registres.relever_expiration("2026-10-11T00:00:00+00:00")
        assert abandonnees == ["vieille"]
        fiche = registres.tache("vieille")
        assert fiche["etat"] == EtatTache.ABANDONNEE.value  # marquée, pas supprimée
        assert fiche["motif"] != ""
        assert registres.tache("future")["etat"] == EtatTache.ATTENTE.value
        with pytest.raises(ValueError):
            registres.passer_etat("future", EtatTache.ABANDONNEE)  # motif exigé
        with pytest.raises(ValueError):
            registres.passer_etat("fantome", EtatTache.COURS)


def test_expiration_horloge_illisible_ne_leve_jamais(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.creer_tache("naive", "ingest", 10.0, "2020-01-01T00:00:00")
        registres.creer_tache("pourrie", "ingest", 10.0, "pas-une-date")
        assert registres.relever_expiration("pas-une-horloge") == []
        assert registres.relever_expiration("2026-10-11T00:00:00+00:00") == []
        assert registres.tache("naive")["etat"] == EtatTache.ATTENTE.value
        assert registres.tache("pourrie")["etat"] == EtatTache.ATTENTE.value


def test_curseurs_persistes(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        assert registres.curseur("local_files") is None
        registres.noter_curseur("local_files", "2026-10-11T00:00:00+00:00")
        assert registres.curseur("local_files") == "2026-10-11T00:00:00+00:00"


def test_snapshot_registres_recharge(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.noter_source("s1", {"n": 1})
        registres.definir_alias("code", "a", ["b"])
        registres.creer_tache("t1", "ingest", 5.0, "2030-01-01T00:00:00+00:00")
        registres.noter_curseur("local_files", "curseur-1")
        for flux in ("registry/sources", "registry/aliases", "registry/tasks"):
            magasin.snapshot(flux)
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        assert registres.source("s1") == {"n": 1}
        assert registres.alias("code", "a") == ["b"]
        assert registres.tache("t1")["etat"] == EtatTache.ATTENTE.value
        assert registres.curseur("local_files") == "curseur-1"


def test_taches_et_curseurs_cohabitent(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        registres = Registres(magasin)
        registres.creer_tache("t1", "ingest", 5.0, "2020-01-01T00:00:00+00:00")
        registres.noter_curseur("local_files", "curseur-1")
        abandonnees = registres.relever_expiration("2026-10-11T00:00:00+00:00")
        assert abandonnees == ["t1"]  # le curseur n'est pas une tâche
        assert registres.curseur("local_files") == "curseur-1"
