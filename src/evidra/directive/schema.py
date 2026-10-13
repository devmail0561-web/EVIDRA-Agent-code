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

LONGUEUR_REGEX_MAX = 200
"""Borne anti-ReDoS des motifs de surveillance ([provisoire], T7.1)."""


class _Base(BaseModel):
    model_config = _CONFIG


class Budgets(_Base):
    """Budgets par cycle (scheduler T1.5, directive T4.4)."""

    max_tool_calls: int = Field(default=6, ge=1)
    max_ingest_per_cycle: int | None = Field(default=None, ge=1)
    max_cycle_ms: float | None = Field(default=None, gt=0.0, allow_inf_nan=False)
    max_wal_bytes: int | None = Field(default=None, gt=0)
    reserve_fond: int = Field(default=1, ge=0)
    timeout_travailleur_s: float = Field(
        default=30.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] timeout workers extract/reason/Rust (T1.5)",
    )
    timeout_http_s: float = Field(
        default=5.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] timeout requêtes HTTP flux (T9.8)",
    )
    backoff_plafond_s: float = Field(
        default=300.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] plafond du backoff flux (T9.8)",
    )
    attente_boucle_s: float = Field(
        default=0.05,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] attente entre ticks à vide (T4.4)",
    )
    fsync_batch_lignes: int = Field(
        default=100, ge=1, description="[provisoire] fsync WAL toutes les N lignes (T2.1)"
    )
    fsync_batch_ms: float = Field(
        default=1000.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] fsync WAL au plus tous les N ms (T2.1)",
    )
    cache_taille_max: int = Field(
        default=1024, ge=1, description="[provisoire] entrées max du cache requêtes LRU (T5.6)"
    )
    file_max: int = Field(
        default=1000,
        ge=1,
        le=100_000,
        description="[provisoire] événements externes en attente max (API)",
    )


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

    stale_after_days: float = Field(
        default=30.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] STALE après N jours (étude : CTI 30 j)",
    )
    invalidate_after_days: float = Field(
        default=90.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] INVALIDÉE après N jours sans re-confirm.",
    )
    retention_jours: int | None = Field(
        default=None, ge=1, description="T9.10 : purge des preuves après délai (None = conserver)"
    )


class Provisoire(_Base):
    """Constantes d'arbitrage — TOUTES `[provisoire]` (I9), calibration T10.3."""

    t_domaine: float = Field(
        default=30.0,
        gt=0.0,
        allow_inf_nan=False,
        description="[provisoire] constante de temps (jours, demi-vie = T·ln2)",
    )
    nmax: float | int = Field(
        default=50, gt=0, description="[provisoire] saturation Nmax (norm_conf)"
    )
    seuil_quorum: float = Field(
        default=2.0, gt=1.0, description="[provisoire] ratio > seuil ⇒ l'arête l'emporte"
    )
    seuil_revision: float = Field(
        default=3.0, gt=1.0, description="[provisoire] ratio ≤ seuil ⇒ EN RÉVISION (amendement)"
    )
    n_confirmation: int = Field(
        default=3, ge=2, description="[provisoire] confirmations ⇒ CONFIRMÉE (T6.1)"
    )
    poids_confirmation: float = Field(
        default=0.7, ge=0.0, le=1.0, description="[provisoire] fiabilité source (T6.3)"
    )
    n_min_source: int = Field(
        default=5, ge=1, description="[provisoire] plancher effectif fiabilité (T6.3)"
    )
    seuil_confiance_source: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="[provisoire] trusted si ≥ et contradiction ≤ plafond",
    )
    plafond_contradiction: float = Field(
        default=0.05, ge=0.0, le=1.0, description="[provisoire] trusted si contradiction ≤ (T6.3)"
    )
    seuil_suspect: float = Field(
        default=0.10, ge=0.0, le=1.0, description="[provisoire] contradiction > ⇒ suspect (T6.3)"
    )
    plancher_surveillee: float = Field(
        default=0.60, ge=0.0, le=1.0, description="[provisoire] monitored dès (T6.3)"
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

    min_confidence: float = Field(
        default=0.70, ge=0.0, le=1.0, description="seuil d'admission (étude §7 : 0.70)"
    )
    min_extraction_method: str | list[str] = Field(
        default="symbolic_rust", description="méthode exigée (vocabulaire moteur constaté)"
    )
    seuils_tiers: tuple[float, float] = Field(
        default=(0.85, 0.65),
        description="[provisoire] tiers confiance index (high, medium), étude §7.2",
    )
    limite_repli_lexical: int = Field(
        default=50, ge=1, description="[provisoire] borne du repli sous-chaîne (T2.5)"
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


def n_confirmation_defaut() -> int:
    """Défaut canonique des confirmations (source unique : `Provisoire`, I9)."""
    return int(Provisoire.model_fields["n_confirmation"].default)


def limite_repli_defaut() -> int:
    """Borne canonique du repli lexical (source unique : `Qualite`, I9)."""
    return int(Qualite.model_fields["limite_repli_lexical"].default)


def timeout_travailleur_defaut() -> float:
    """Timeout canonique workers extract/reason/Rust (source unique : `Budgets`, I9)."""
    return float(Budgets.model_fields["timeout_travailleur_s"].default)


def timeout_egress_defaut() -> float:
    """Timeout canonique egress alertes (source unique : `Surveillance`, I9)."""
    return float(Surveillance.model_fields["timeout_egress_s"].default)


def fenetre_alertes_defaut() -> int:
    """Fenêtre canonique dédup alertes (source unique : `Surveillance`, I9)."""
    return int(Surveillance.model_fields["dedup_fenetre_s"].default)


def alertes_rapport_max_defaut() -> int:
    """Nombre canonique d'alertes par reçu (source unique : `Surveillance`, I9)."""
    return int(Surveillance.model_fields["alertes_rapport_max"].default)


def timeout_api_defaut() -> float:
    """Timeout canonique réponse scheduler (source unique : `ApiConfig`, I9)."""
    return float(ApiConfig.model_fields["timeout_s"].default)


def timeout_http_defaut() -> float:
    """Timeout canonique requêtes HTTP flux (source unique : `Budgets`, I9)."""
    return float(Budgets.model_fields["timeout_http_s"].default)


def backoff_plafond_defaut() -> float:
    """Plafond canonique du backoff flux (source unique : `Budgets`, I9)."""
    return float(Budgets.model_fields["backoff_plafond_s"].default)


def attente_boucle_defaut() -> float:
    """Attente canonique entre ticks à vide (source unique : `Budgets`, I9)."""
    return float(Budgets.model_fields["attente_boucle_s"].default)


def fsync_batch_lignes_defaut() -> int:
    """Lignes canoniques entre fsync WAL (source unique : `Budgets`, I9)."""
    return int(Budgets.model_fields["fsync_batch_lignes"].default)


def fsync_batch_ms_defaut() -> float:
    """Délai canonique entre fsync WAL (source unique : `Budgets`, I9)."""
    return float(Budgets.model_fields["fsync_batch_ms"].default)


def cache_taille_max_defaut() -> int:
    """Taille canonique du cache LRU (source unique : `Budgets`, I9)."""
    return int(Budgets.model_fields["cache_taille_max"].default)


def file_max_defaut() -> int:
    """File d'événements canonique (source unique : `Budgets`, I9)."""
    return int(Budgets.model_fields["file_max"].default)


def profondeur_gaps_defaut() -> int:
    """Profondeur canonique des lacunes (source unique : `Surveillance`, I9)."""
    return int(Surveillance.model_fields["profondeur_gaps"].default)


def limite_section_defaut() -> int:
    """Limite canonique de section de rapport (source unique : `Sortie`, I9)."""
    return int(Sortie.model_fields["limite_section"].default)


class Surveillance(_Base):
    """Conditions du moniteur (phase 7 ; regex validées anti-ReDoS)."""

    watch_cycles: bool = False
    watch_gaps_in_chains: list[list[str]] = Field(
        default_factory=list, description="chaînes surveillées (nœuds, T7.3)"
    )
    alert_on_new_relation_involving: list[str] = Field(default_factory=list)
    dedup_fenetre_s: int = Field(
        default=3600, ge=0, description="[provisoire] non réémission d'une alerte (T7.2)"
    )
    alert_endpoint: str | None = Field(
        default=None, description="egress optionnel des alertes (T7.2, hors ligne ⇒ dégradé)"
    )
    seuil_invalidation: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="[provisoire] haute confiance invalidée ⇒ critique (T7.1)",
    )
    timeout_egress_s: float = Field(
        default=5.0, gt=0.0, description="[provisoire] timeout envoi alertes (T7.2, best-effort)"
    )
    alertes_rapport_max: int = Field(
        default=5, ge=1, description="[provisoire] alertes retenues par reçu de boucle (T4.4)"
    )
    profondeur_gaps: int = Field(
        default=1, ge=1, description="[provisoire] profondeur BFS des lacunes (T7.3)"
    )

    @field_validator("alert_on_new_relation_involving")
    @classmethod
    def _regex_valides(cls, motifs: list[str]) -> list[str]:
        for motif in motifs:
            try:
                re.compile(motif)
            except re.error:
                raise ValueError(f"regex invalide : {motif!r}") from None
            if len(motif) > LONGUEUR_REGEX_MAX:
                raise ValueError(f"regex trop longue : {motif!r}") from None
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
    egress_hotes: list[str] = Field(
        default_factory=list,
        description="T9.9 : hôtes autorisés en sortie (vide = aucun egress, fail-closed)",
    )
    limite_section: int = Field(
        default=100, ge=1, description="[provisoire] faits par section de rapport (T5.8)"
    )


class AgentPair(_Base):
    """Agent pair autorisé (autorité d'écriture, §8.5)."""

    agent_id: str = Field(min_length=1)
    domains: list[str] = Field(default_factory=list)
    max_confidence_accepted: float = Field(
        default=1.0, ge=0.0, le=1.0, description="plafond accepté (neutre 1.0 = aucun, T9.3)"
    )
    cle_id: str = Field(
        default="", description="clé HMAC (api.cles_directive), vide = rejet (T9.3)"
    )


class JetonApi(_Base):
    """Jeton porteur : empreinte SHA-256 (jamais le secret), verbes liés (T8.3)."""

    nom: str = Field(min_length=1)
    empreinte: str = Field(min_length=16, description="hex SHA-256 du jeton")
    verbes: list[Verb] = Field(default_factory=list)


class ApiConfig(_Base):
    """Exposition HTTP (T8.3) : vide = ouvert dev/dogfood (documenté)."""

    jetons: list[JetonApi] = Field(default_factory=list)
    cles_directive: dict[str, str] = Field(
        default_factory=dict,
        description="clé_id → secret HMAC (fichier 0600, jamais repo, T8.3)",
    )
    timeout_s: float = Field(
        default=5.0, gt=0.0, description="[provisoire] attente réponse scheduler (T8.1)"
    )


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
    deduction: Literal["disabled", "enabled"] = Field(
        default="disabled", description="gate T6.6 : déduction tracée interdite par défaut"
    )
    semantic_index_min_edges: int = Field(default=500000, gt=0)
    trusted_agents: list[AgentPair] = Field(default_factory=list)
    api: ApiConfig = Field(default_factory=ApiConfig)

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
