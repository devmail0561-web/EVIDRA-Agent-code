# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.2 — manifeste : accepté si complet et bien formé, refusé sinon."""

from __future__ import annotations

from typing import Any

import pytest

from evidra.kernel.contracts import CostHint, Verb
from evidra.kernel.manifest import (
    ManifestError,
    manifest_from_plugin,
    parse_version,
    validate_manifest,
)


def _brut(**surcharges: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "factice",
        "version": "0.1.0",
        "harness_required": "1.0",
        "permissions": [{"verb": "read", "scope": "*"}],
        "channels": ["test"],
        "cost_hint": {"ms": 1.0, "calls": 1},
        "input_schema": {},
        "output_schema": {},
        "requires_network": False,
    }
    base.update(surcharges)
    return base


def test_manifeste_valide_accepte():
    manifeste = validate_manifest(_brut())
    assert manifeste.name == "factice"
    assert manifeste.version == "0.1.0"
    assert manifeste.cost_hint == CostHint(ms=1.0, calls=1)
    assert manifeste.requires_network is False


def test_manifeste_non_objet_refuse():
    with pytest.raises(ManifestError):
        validate_manifest(["pas-un-objet"])  # type: ignore[arg-type]


@pytest.mark.parametrize("champ", ["name", "version", "channels", "requires_network"])
def test_champ_manquant_refuse(champ: str):
    brut = _brut()
    del brut[champ]
    with pytest.raises(ManifestError):
        validate_manifest(brut)


@pytest.mark.parametrize("version", ["1.0", "v1.2.3", "1.2.3.4.5", "", "derniere"])
def test_version_non_semver_refusee(version: str):
    with pytest.raises(ManifestError):
        validate_manifest(_brut(version=version))


@pytest.mark.parametrize("verbe", ["lire", "", "READ", None])
def test_verbe_inconnu_refuse(verbe: Any):
    with pytest.raises(ManifestError):
        validate_manifest(_brut(permissions=[{"verb": verbe, "scope": "*"}]))


def test_scope_vide_refuse():
    with pytest.raises(ManifestError):
        validate_manifest(_brut(permissions=[{"verb": "read", "scope": ""}]))


def test_parse_version():
    assert parse_version("1.0") == (1, 0)
    assert parse_version("1.0.3") == (1, 0, 3)
    assert parse_version("x") is None
    assert parse_version("") is None


class _PluginBon:
    name = "bon"
    version = "0.2.0"
    harness_required = "1.0"
    permissions = [{"verb": "read", "scope": "*"}]
    channels = ["test"]
    cost_hint = {"ms": 2.0, "calls": 1}
    input_schema: dict[str, Any] = {}
    output_schema: dict[str, Any] = {}
    requires_network = True


class _PluginSansVersion:
    name = "sans-version"


def test_depuis_classe_conforme():
    manifeste = manifest_from_plugin(_PluginBon)
    assert manifeste.version == "0.2.0"
    assert manifeste.requires_network is True


def test_depuis_classe_incomplete_refuse():
    with pytest.raises(ManifestError):
        manifest_from_plugin(_PluginSansVersion)


def test_verbe_enum_couvert():
    assert {v.value for v in Verb} == {"read", "ingest", "modify", "delete", "alert", "egress"}
