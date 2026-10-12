# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T4.1 — schéma : dogfood valide, invalides précis, provisoire marqué."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidra.directive.schema import Directive, schema_json, valider
from evidra.kernel.contracts import Verb
from evidra.kernel.gate import can
from evidra.logging import DirectiveError

RACINE = Path(__file__).resolve().parent.parent.parent
SCHEMA_COMMIS = RACINE / "docs" / "contrats" / "directive.schema.json"
DOGFOOD = RACINE / "directives" / "code.dogfood.json"


def _dogfood() -> dict:
    return json.loads(DOGFOOD.read_text(encoding="utf-8"))


def test_dogfood_valide() -> None:
    directive = valider(_dogfood())
    assert isinstance(directive, Directive)
    assert directive.domain == "code"
    assert directive.quality.min_confidence == 0.0
    assert directive.delegate == "disabled"


def test_invalide_chemin_precis() -> None:
    with pytest.raises(DirectiveError, match="domain"):
        valider({"agent_id": "x"})
    with pytest.raises(DirectiveError):
        valider("pas-un-objet")  # type: ignore[arg-type]
    with pytest.raises(DirectiveError, match="min_confidence"):
        valider({**_dogfood(), "quality": {"min_confidence": 1.5}})
    with pytest.raises(DirectiveError):
        valider({**_dogfood(), "champ_inconnu": 1})  # extra=forbid
    with pytest.raises(DirectiveError, match="delegate"):
        valider({**_dogfood(), "delegate": "actif"})
    with pytest.raises(DirectiveError):
        valider({**_dogfood(), "seuils_provisoires": {"seuil_quorum": 2.0, "seuil_revision": 1.5}})
    with pytest.raises(DirectiveError, match="alert_on_new_relation_involving"):
        valider({**_dogfood(), "monitoring": {"alert_on_new_relation_involving": ["(["]}})


def test_valeurs_provisoires_etiquetees() -> None:
    schema = json.dumps(schema_json())
    for champ in ("t_domaine", "nmax", "seuil_quorum", "seuil_revision", "channel_ceilings"):
        assert champ in schema
    assert schema.count("[provisoire]") >= 5


def test_schema_commis_a_jour() -> None:
    commis = json.loads(SCHEMA_COMMIS.read_text(encoding="utf-8"))
    assert commis == schema_json()


def test_politique_branchee_sur_can() -> None:
    directive = valider(
        {
            **_dogfood(),
            "permissions": {"allowed": [{"tool": "ingest", "verb": "ingest", "scope": "code"}]},
        }
    )
    politique = directive.permissions.en_politique()
    assert can(politique, "ingest", Verb.INGEST, "code")
    assert not can(politique, "ingest", Verb.DELETE, "code")
