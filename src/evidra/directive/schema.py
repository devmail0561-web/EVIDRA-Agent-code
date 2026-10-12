# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Schéma de directive (T4.1, Pydantic v2 aux bords — ADR-0004).

Couvre §9.3 + ajouts : budgets, quotas, plafonds de canal, alias, permissions,
staleness, constantes `provisoire` (étiquetées `[provisoire]` dans le schéma,
I9), `delegate: disabled` (gate P3), `semantic_index_min_edges`, agents de
confiance. `extra="forbid"` : champ inconnu = directive invalide (fail-closed).
`valider()` lève `DirectiveError` précis (chemin du champ).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from evidra.kernel.contracts import Verb
from evidra.kernel.gate import Policy, Rule
from evidra.logging import DirectiveError

_CONFIG = ConfigDict(extra="forbid")


class _Base(BaseModel):
    model_config = _CONFIG


class Budgets(_Base):
    """Budgets par cycle (scheduler T1.5, directive T4.4)."""

    max_tool_calls: int = Field(default=6, ge=1)
    max_ingest_per_cycle: int | None = Field(default=None, ge=1)
    max_cycle_ms: float | None = Field(default=None, gt=0.0)
    max_wal_bytes: int | None = Field(default=None, gt=0)
    reserve_fond: int = Field(default=1, ge=0)


class PermissionDirective(_Base):
    """Une règle : outil (`*` = tous), verbe, périmètre (`*` = tous)."""

    tool: str = "*"
    verb: Verb
    scope: str = Field(min_length=1)


class Permissions(_Base):
    """Matrice `allowed`/`forbidden` (porte `can()`, T1.4)."""

    allowed: list[PermissionDirective] = Field(default_factory=list)
    forbidden: list[PermissionDirective] = Field(default_factory=list)

    def en_politique(self) -> Policy:
        """Vers la matrice pure du noyau."""
        return Policy(
            allowed=frozenset(Rule(r.tool, r.verb, r.scope) for r in self.allowed),
            forbidden=frozenset(Rule(r.tool, r.verb, r.scope) for r in self.forbidden),
        )


class Staleness(_Base):
    """Rythme de vieillissement du domaine (jours)."""

    stale_after_days: float = Field(default=30.0, gt=0.0)
    invalidate_after_days: float = Field(default=90.0, gt=0.0)


class Provisoire(_Base):
    """Constantes d'arbitrage — TOUTES `[provisoire]` (I9), calibration T10.3."""

    t_domaine: float = Field(
        default=30.0,
        gt=0.0,
        description="[provisoire] constante de temps (jours, demi-vie = T·ln2)",
    )
    nmax: float | int = Field(default=50, description="[provisoire] saturation Nmax (norm_conf)")
    seuil_quorum: float = Field(
        default=2.0, gt=1.0, description="[provisoire] ratio > seuil ⇒ l'arête l'emporte"
    )
    seuil_revision: float = Field(
        default=3.0, gt=1.0, description="[provisoire] ratio ≤ seuil ⇒ EN RÉVISION (amendement)"
    )

    @model_validator(mode="after")
    def _coherent(self) -> Provisoire:
        if self.seuil_revision < self.seuil_quorum:
            raise ValueError("seuil_revision >= seuil_quorum exigé")
        return self


class Source(_Base):
    """Source externe : adaptateur interchangeable + config (non hardcodée)."""

    adapter: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class Qualite(_Base):
    """Seuils d'admission (ingest T3.6 ; mapping méthode en T4.1+)."""

    min_confidence: float = Field(default=0.70, ge=0.0, le=1.0)
    min_extraction_method: str | list[str] = "symbolic_rust"
    seuils_tiers: tuple[float, float] = Field(
        default=(0.85, 0.65),
        description="[provisoire] tiers confiance index (high, medium), étude §7.2",
    )

    @field_validator("seuils_tiers")
    @classmethod
    def _tiers_ordonnes(cls, seuils: tuple[float, float]) -> tuple[float, float]:
        haut, moyen = seuils
        if not 0.0 <= moyen <= haut <= 1.0:
            raise ValueError("seuils_tiers exige 0 ≤ medium ≤ high ≤ 1")
        return seuils


def seuils_tiers_defaut() -> tuple[float, float]:
    """Défaut canonique des tiers (source unique : `Qualite.seuils_tiers`, I9)."""
    defaut = Qualite.model_fields["seuils_tiers"].default
    return (float(defaut[0]), float(defaut[1]))


class Surveillance(_Base):
    """Conditions du moniteur (phase 7 ; regex validées anti-ReDoS)."""

    watch_cycles: bool = False
    watch_gaps_in_chains: list[str] = Field(default_factory=list)
    alert_on_new_relation_involving: list[str] = Field(default_factory=list)

    @field_validator("alert_on_new_relation_involving")
    @classmethod
    def _regex_valides(cls, motifs: list[str]) -> list[str]:
        for motif in motifs:
            try:
                re.compile(motif)
            except re.error:
                raise ValueError(f"regex invalide : {motif!r}") from None
            if len(motif) > 200:
                raise ValueError(f"regex trop longue : {motif!r}")
        return motifs


class Actions(_Base):
    """Actions autorisées/interdites à l'agent."""

    allowed: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)


class Sortie(_Base):
    """Formats et destinations (egress réseau = verbe contrôlé, T9.9)."""

    default_format: str = "json"
    alert_endpoint: str = ""
    report_schedule: str = ""


class AgentPair(_Base):
    """Agent pair autorisé (autorité d'écriture, §8.5)."""

    agent_id: str = Field(min_length=1)
    domains: list[str] = Field(default_factory=list)
    max_confidence_accepted: float = Field(default=1.0, ge=0.0, le=1.0)


class Directive(_Base):
    """Directive : mission complète d'un agent sur un domaine (§9.3)."""

    agent_id: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    sources: list[Source] = Field(default_factory=list)
    quality: Qualite = Field(default_factory=Qualite)
    staleness: Staleness = Field(default_factory=Staleness)
    monitoring: Surveillance = Field(default_factory=Surveillance)
    actions: Actions = Field(default_factory=Actions)
    output: Sortie = Field(default_factory=Sortie)
    budgets: Budgets = Field(default_factory=Budgets)
    permissions: Permissions = Field(default_factory=Permissions)
    channel_ceilings: dict[str, float] = Field(
        default_factory=dict,
        description="[provisoire] plafonds par canal, confiances non calibrées (B1)",
    )
    aliases: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict, description="table d'alias par domaine (promotion humaine, §19)"
    )
    seuils_provisoires: Provisoire = Field(default_factory=Provisoire)
    delegate: Literal["disabled"] = Field(
        default="disabled", description="gate P3 : toute autre valeur refusée avant T10.7"
    )
    semantic_index_min_edges: int = Field(default=500000, gt=0)
    trusted_agents: list[AgentPair] = Field(default_factory=list)

    @field_validator("channel_ceilings")
    @classmethod
    def _plafonds(cls, plafonds: dict[str, float]) -> dict[str, float]:
        for canal, plafond in plafonds.items():
            if not 0.0 <= plafond <= 1.0:
                raise ValueError(f"plafond {canal!r} hors [0,1]")
        return plafonds


def valider(donnees: Mapping[str, Any]) -> Directive:
    """Valide une directive brute ; `DirectiveError` précis sinon."""
    if not isinstance(donnees, Mapping):
        raise DirectiveError("directive invalide : objet exigé")
    try:
        return Directive(**dict(donnees))
    except ValidationError as exc:
        premier = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in premier.get("loc", ()))
        raise DirectiveError(
            f"directive invalide : {loc or '?'} : {premier.get('msg', exc)}"
        ) from None


def schema_json() -> dict[str, Any]:
    """JSON Schema exportable (`docs/contrats/directive.schema.json`)."""
    return Directive.model_json_schema()
