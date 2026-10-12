# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T8.3 — jetons, verbes, directive signée, rollback (extras `api`+`network`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from evidra.api.app import creer_app  # noqa: E402
from evidra.api.auth import (  # noqa: E402
    Autheur,
    autheur_depuis_directive,
    canonique,
    empreinte_jeton,
    signer,
)
from evidra.api.pont import contexte_depuis_rapport  # noqa: E402
from evidra.boot.demarrage import demarrer  # noqa: E402
from evidra.directive.loader import charger  # noqa: E402
from evidra.kernel.contracts import Verb  # noqa: E402

LECTURE = "jeton-lecture-abc"
ECRITURE = "jeton-ecriture-def"
CLE_OWNER = "cle-owner-secrete"


def _directive() -> dict:
    return {
        "agent_id": "t",
        "domain": "code",
        "permissions": {
            "allowed": [
                {"tool": "*", "verb": "read", "scope": "*"},
                {"tool": "*", "verb": "ingest", "scope": "*"},
                {"tool": "*", "verb": "modify", "scope": "*"},
            ]
        },
        "api": {
            "jetons": [
                {"nom": "lecture", "empreinte": empreinte_jeton(LECTURE), "verbes": ["read"]},
                {
                    "nom": "ecriture",
                    "empreinte": empreinte_jeton(ECRITURE),
                    "verbes": ["read", "ingest", "modify"],
                },
            ],
            "cles_directive": {"owner1": CLE_OWNER},
        },
    }


def _app(tmp_path: Path) -> tuple[TestClient, Path]:
    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(json.dumps(_directive()), encoding="utf-8")
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.boucle is not None and rapport.magasin is not None
    api = contexte_depuis_rapport(rapport, data)
    assert api is not None
    autheur = autheur_depuis_directive(charger(directive))
    assert autheur is not None
    app = creer_app(rapport.boucle, api, autheur=autheur, directive_path=directive)
    return TestClient(app), directive


def _porteur(secret: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def test_sans_jeton_401(tmp_path: Path) -> None:
    with _app(tmp_path)[0] as client:
        assert client.get("/query/causes/x").status_code == 401
        assert client.post("/validate", json={"claim": "x y"}).status_code == 401


def test_jeton_inconnu_401(tmp_path: Path) -> None:
    with _app(tmp_path)[0] as client:
        assert client.get("/query/causes/x", headers=_porteur("nope")).status_code == 401


def test_lecture_ok_mais_ingest_403(tmp_path: Path) -> None:
    with _app(tmp_path)[0] as client:
        assert client.get("/query/causes/x", headers=_porteur(LECTURE)).status_code == 200
        # Auth avant handler : 403 même sans moteur (pas 503).
        r = client.post("/ingest", json={"textes": ["p."]}, headers=_porteur(LECTURE))
        assert r.status_code == 403


def test_verbes_temps_constant() -> None:
    autheur = Autheur(empreintes=(("n", "e" * 64, frozenset({Verb.READ})),), cles=())
    assert autheur.verbes_jeton("x") is None and autheur.nom_jeton("x") is None


def _signature(directive: dict) -> str:
    return "owner1:" + signer(CLE_OWNER, canonique(directive))


def test_directive_signee_publiee_et_rollback(tmp_path: Path) -> None:
    client, directive = _app(tmp_path)
    with client:
        base = json.loads(directive.read_text(encoding="utf-8"))
        assert client.post("/directive", json={"directive": base, "motif": "t"}).status_code == 401
        use = dict(base)
        use["semantic_index_min_edges"] = 600000
        mauvais = {"directive": use, "motif": "t", "signature": "owner1:00"}

        def post(corps: dict) -> httpx.Response:
            return client.post("/directive", json=corps, headers=_porteur(ECRITURE))

        assert post(mauvais).status_code == 403
        bon = {"directive": use, "motif": "t", "signature": _signature(use)}
        assert post(bon).status_code == 200
        publiee = json.loads(directive.read_text(encoding="utf-8"))
        assert publiee["semantic_index_min_edges"] == 600000
        corps = canonique({"rollback": True, "motif": "annule"})
        sig = "owner1:" + signer(CLE_OWNER, corps)
        rollback = {"motif": "annule", "signature": sig}
        url = "/directive/rollback"
        assert client.post(url, json=rollback, headers=_porteur(ECRITURE)).status_code == 200
        assert json.loads(directive.read_text(encoding="utf-8")) == base


def test_directive_invalide_422(tmp_path: Path) -> None:
    client, _directive = _app(tmp_path)
    with client:
        use = {"agent_id": "t"}
        bon = {"directive": use, "motif": "t", "signature": _signature(use)}
        assert client.post("/directive", json=bon, headers=_porteur(ECRITURE)).status_code == 422


def test_signer_verifier_unitaire() -> None:
    autheur = Autheur(empreintes=(), cles=(("k", "s3cr3t"),))
    assert autheur.verifier_signature("k", b"corps", signer("s3cr3t", b"corps")) is True
    assert autheur.verifier_signature("k", b"corps", signer("s3cr3t", b"autre")) is False
    assert autheur.verifier_signature("inconnue", b"corps", "00") is False
