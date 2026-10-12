# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T8.1/T8.2/T8.4/T8.5 — endpoints, contrats, charge concurrente.

Requiert les extras `api` + `network` (`uv run --extra api --extra network
pytest tests/api`) ; sautés sinon (importorskip).
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from evidra.api.app import creer_app  # noqa: E402
from evidra.api.pont import contexte_depuis_rapport  # noqa: E402
from evidra.boot.demarrage import demarrer  # noqa: E402
from evidra.kernel.contracts import Context  # noqa: E402
from evidra.memory.envelope import CirCore, Provenance  # noqa: E402


def _directive() -> dict:
    return {
        "agent_id": "t",
        "domain": "code",
        "permissions": {
            "allowed": [
                {"tool": "*", "verb": "read", "scope": "*"},
                {"tool": "*", "verb": "ingest", "scope": "*"},
                {"tool": "*", "verb": "alert", "scope": "*"},
            ]
        },
    }


def _noyau(ref: str) -> CirCore:
    return CirCore(
        source="Surchauffe",
        target="panne",
        relation="cause",
        confidence=0.9,
        provenance=Provenance(
            ref=ref,
            span="synthetic",
            extraction_method="symbolic_rust",
            model_version="v",
            extracted_at="t",
        ),
    )


def _app(tmp_path: Path) -> TestClient:
    data = tmp_path / "data"
    directive = tmp_path / "directive.json"
    directive.write_text(json.dumps(_directive()), encoding="utf-8")
    rapport = demarrer(data_dir=data, directive_path=directive)
    assert rapport.ingest is not None and rapport.magasin is not None and rapport.boucle is not None
    ctx = Context(store=rapport.magasin, domain="code")
    rapport.ingest.run(ctx, {"noyaux": [_noyau("doc://1")], "channel": "t"})
    api = contexte_depuis_rapport(rapport, data)
    assert api is not None
    return TestClient(creer_app(rapport.boucle, api))


def test_query_causes_contrat(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        r = client.get("/query/causes/surchauffe")
        assert r.status_code == 200
        corps = r.json()
        assert corps["status"] == "ok" and corps["format"] == "llm"
        assert corps["donnees"]["faits"] != []


def test_formats_et_erreurs(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        assert client.get("/query/causes/surchauffe?format=human").status_code == 200
        assert client.get("/query/effects/surchauffe?format=agent").status_code == 200
        assert client.get("/query/causes/surchauffe?format=xml").status_code == 422
        assert client.get("/query/effects/inconnu-xyz").json()["status"] == "ok"


def test_validate_et_status_et_alerts(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        claim = {"source": "x", "relation": "cause", "cible": "y"}
        r = client.post("/validate", json={"claim": claim})
        assert r.status_code == 200 and r.json()["payload"]["verdict"] == "UNCONFIRMED"
        assert client.get("/status").status_code == 200
        assert client.get("/status").json()["payload"]["etat"]["manifeste"] is not None
        assert client.get("/alerts").status_code == 200


def test_sans_moteur_503(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        assert client.post("/analyze", json={"textes": ["phrase."]}).status_code == 503
        assert client.post("/ingest", json={"textes": ["phrase."]}).status_code == 503


def test_charge_concurrente_sans_corruption(tmp_path: Path) -> None:
    def frappe(_i: int) -> int:
        return client.get("/query/causes/surchauffe").status_code

    with _app(tmp_path) as client:
        with ThreadPoolExecutor(max_workers=8) as pool:
            codes = list(pool.map(frappe, range(32)))
        assert codes == [200] * 32


def test_openapi_expose(tmp_path: Path) -> None:
    with _app(tmp_path) as client:
        schema = client.get("/openapi.json").json()
        chemins = set(schema["paths"])
        assert {"/analyze", "/ingest", "/validate", "/status", "/alerts"} <= chemins
        assert "/query/causes/{concept}" in chemins
