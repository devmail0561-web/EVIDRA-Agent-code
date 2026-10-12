# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T3.7 — local_files : poll, curseur/reprise, lecture seule, spans."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from evidra.adapters.local_files import AdaptateurFichiers
from evidra.kernel.contracts import Adapter, RawDoc
from evidra.kernel.manifest import manifest_from_plugin
from evidra.memory.envelope import CodeSpan, TokenSpan


def _racine(tmp_path: Path) -> Path:
    racine = tmp_path / "sources"
    (racine / "docs").mkdir(parents=True)
    (racine / "docs" / "note.md").write_text("# Note\nLes ventes baissent.\n", encoding="utf-8")
    (racine / "outil.py").write_text("x = 1\n", encoding="utf-8")
    (racine / ".git").mkdir()
    (racine / ".git" / "gros.md").write_text("ignoré\n", encoding="utf-8")
    return racine


def test_poll_initial_conforme(tmp_path: Path) -> None:
    adaptateur = AdaptateurFichiers(_racine(tmp_path))
    assert isinstance(adaptateur, Adapter)
    assert adaptateur.requires_network is False
    docs = adaptateur.poll(None)
    assert len(docs) == 2
    assert all(isinstance(d, RawDoc) for d in docs)
    uris = sorted(d.uri for d in docs)
    assert uris[0].endswith("docs/note.md") and uris[1].endswith("outil.py")
    note = next(d for d in docs if d.uri.endswith("note.md"))
    assert note.channel == "local_files" and note.published_at
    assert manifest_from_plugin(AdaptateurFichiers).name == "local_files"


def test_modification_un_seul_doc(tmp_path: Path) -> None:
    racine = _racine(tmp_path)
    adaptateur = AdaptateurFichiers(racine)
    assert len(adaptateur.poll(None)) == 2
    curseur = adaptateur.curseur()
    time.sleep(0.02)
    (racine / "docs" / "note.md").write_text("# Note\nLes ventes chutent.\n", encoding="utf-8")
    docs = adaptateur.poll(curseur)
    assert len(docs) == 1
    assert docs[0].uri.endswith("docs/note.md")
    assert "chutent" in docs[0].text


def test_reprise_sans_retraitement(tmp_path: Path) -> None:
    racine = _racine(tmp_path)
    premier = AdaptateurFichiers(racine)
    premier.poll(None)
    curseur = premier.curseur()
    premier.ack(curseur)
    second = AdaptateurFichiers(racine)
    assert second.poll(curseur) == []
    troisieme = AdaptateurFichiers(racine)
    assert len(troisieme.poll("corrompu{")) == 2  # curseur illisible ⇒ re-scan toléré


def test_lecture_seule_aucun_sidecar(tmp_path: Path) -> None:
    racine = _racine(tmp_path)
    avant = sorted(p.name for p in racine.rglob("*"))
    adaptateur = AdaptateurFichiers(racine)
    adaptateur.poll(None)
    adaptateur.ack(adaptateur.curseur())
    assert sorted(p.name for p in racine.rglob("*")) == avant
    assert not (racine / "sa.lock").exists()


def test_binaire_saute(tmp_path: Path) -> None:
    racine = _racine(tmp_path)
    (racine / "docs" / "image.txt").write_bytes(b"\xff\xfe\x00binaire")
    adaptateur = AdaptateurFichiers(racine)
    docs = adaptateur.poll(None)
    assert len(docs) == 2
    assert all(d.uri.endswith((".md", ".py")) for d in docs)


def test_etendue_token_code() -> None:
    adaptateur = AdaptateurFichiers(".")
    span = adaptateur.etendue("bonjour monde", code=False)
    assert isinstance(span, TokenSpan) and (span.debut, span.fin) == (0, 13)
    code = adaptateur.etendue("a = 1\nb = 2\n", code=True, fichier="f.py")
    assert isinstance(code, CodeSpan) and (code.fichier, code.ligne_debut, code.ligne_fin) == (
        "f.py",
        1,
        2,
    )


def test_racine_illisible() -> None:
    with pytest.raises(ValueError):
        AdaptateurFichiers("/inexistant-xyz").poll(None)
    with pytest.raises(ValueError):
        AdaptateurFichiers(".").ack("pas-du-json")
