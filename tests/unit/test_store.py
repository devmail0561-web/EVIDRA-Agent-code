# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T2.4 — Store : routage par domaine, isolation, snapshot via rebuild."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from evidra.kernel.contracts import Record, Store
from evidra.memory.store import Magasin, StoreError
from evidra.memory.wal import Enregistrement


def _record(op: str, cle: str, **donnees: Any) -> Record:
    return Record(stream="", op=op, key=cle, data=dict(donnees))


def _appliquer(etat: dict[str, Any], enr: Enregistrement) -> None:
    if enr.op == "tombstone":
        etat.pop(enr.cle, None)
    else:
        etat[enr.cle] = dict(enr.donnees)


def test_append_lookup_par_domaine(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        assert isinstance(magasin, Store)
        seq = magasin.append("domains/code", _record("add", "k1", n=1))
        assert seq == 1
        trouve = magasin.lookup("domains/code", "k1")
        assert trouve is not None and dict(trouve.data) == {"n": 1}
        assert magasin.lookup("domains/code", "absent") is None


def test_isolation_domaines_donnees_et_compteurs(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        magasin.append("domains/a", _record("add", "k", v="a"))
        magasin.append("domains/b", _record("add", "k", v="b"))
        avant_a, avant_b = magasin.acces("domains/a"), magasin.acces("domains/b")
        trouve_a = magasin.lookup("domains/a", "k")
        assert trouve_a is not None
        assert dict(trouve_a.data) == {"v": "a"}
        assert magasin.acces("domains/a") == avant_a + 1
        assert magasin.acces("domains/b") == avant_b  # B jamais touché
        magasin.definir_appliquer("domains/a", _appliquer)
        charge = magasin.recharger("domains/a")
        assert charge.etat == {"k": {"v": "a"}}
        assert magasin.acces("domains/b") == avant_b


def test_sous_domaine_isole_du_parent(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        magasin.append("domains/code", _record("add", "k", v="parent"))
        magasin.append("domains/code/normatif", _record("add", "k", v="sous"))
        parent = magasin.lookup("domains/code", "k")
        sous = magasin.lookup("domains/code/normatif", "k")
        assert parent is not None and sous is not None
        assert dict(parent.data) == {"v": "parent"}
        assert dict(sous.data) == {"v": "sous"}


def test_stream_registre(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        magasin.append("registry/sources", _record("put", "s1", f=0.5))
        assert magasin.lookup("registry/sources", "s1") is not None


@pytest.mark.parametrize(
    "cle", ["code", "autre/code", "domains/", "domains/a/b/c", "domains/../x", "/domains/a", ""]
)
def test_cles_invalides_refusees(tmp_path: Path, cle: str) -> None:
    with Magasin(tmp_path) as magasin, pytest.raises(StoreError):
        magasin.append(cle, _record("add", "k"))


def test_snapshot_rebuild_identique(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        magasin.definir_appliquer("domains/code", _appliquer)
        magasin.append("domains/code", _record("add", "a", n=1))
        magasin.append("domains/code", _record("add", "b", n=2))
        magasin.append("domains/code", _record("tombstone", "a"))
        magasin.snapshot("domains/code")
        assert (tmp_path / "domains" / "code" / "wal.jsonl").stat().st_size == 0
        assert magasin.lookup("domains/code", "b") is not None
        assert magasin.lookup("domains/code", "a") is None
        charge = magasin.recharger("domains/code")
        assert charge.etat == {"b": {"n": 2}}


def test_snapshot_sans_appliquer_refuse(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        magasin.append(
            "registry/sources", Record(stream="registry/sources", op="put", key="s", data={})
        )
        with pytest.raises(StoreError):
            magasin.snapshot("registry/sources")
        with pytest.raises(StoreError):
            magasin.recharger("registry/sources")


def test_deuxieme_magasin_refuse(tmp_path: Path) -> None:
    with Magasin(tmp_path), pytest.raises(StoreError), Magasin(tmp_path) as second:
        second.append("domains/code", _record("add", "k"))


def test_persiste_apres_reouverture(tmp_path: Path) -> None:
    with Magasin(tmp_path) as magasin:
        magasin.append("domains/code", _record("add", "k", v=1))
    with Magasin(tmp_path) as magasin:
        assert magasin.lookup("domains/code", "k") is not None
