# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Détecteurs de contenu (T9.4) : taxonomie fermée, purs, testés.

- `instruction` : injonctions adressées au SA dans un texte cité ;
- `provenance_forgee` : `ref` non résolvable au moment de l'ingestion ;
- `contradiction_fabriquee` : réfutation d'une croyance établie sans preuve
  (fardeau sur l'arrivant — primitive pure, calibration T10) ;
- `saturation` : volume au-delà d'un plafond (renvoi aux budgets T1.5).

Seuils et motifs : `ARBITRAIRE + protocole` (calibrés sur corpus T9.7).
Chaque menace produit un motif nommé, journalisé par l'appelant.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import urlparse

_LOG = logging.getLogger(__name__)

INJONCTIONS = (
    "oublie tes instructions",
    "ignore tes instructions",
    "ignore les instructions",
    "tu dois obéir",
    "tu dois m'obéir",
    "réponds sans vérifier",
    "ne vérifie pas",
    "désactive tes",
    "désactive la vérification",
    "system prompt",
    "prompt système",
    "forget your instructions",
    "ignore your instructions",
    "you must obey",
    "do not verify",
    "disable verification",
)

SCHEMAS_INTERNES = frozenset({"doc", "agent", "api", "derived", "file", "http", "https"})


def detecter_instruction(texte: str) -> str | None:
    """Injonction adressée au SA ? Motif `instruction` ou `None`."""
    if not isinstance(texte, str):
        return None
    bas = texte.casefold()
    for injonction in INJONCTIONS:
        if injonction in bas:
            return "instruction"
    return None


def ref_resolvable(ref: str) -> bool:
    """`ref` résolvable au moment de l'ingestion (pas de réseau ici)."""
    if not isinstance(ref, str) or not ref:
        return False
    try:
        decoupe = urlparse(ref)
    except ValueError:
        return False
    if decoupe.scheme not in SCHEMAS_INTERNES:
        return False
    if decoupe.scheme == "file":
        try:
            return Path(decoupe.path).exists()
        except OSError:
            return False
    if decoupe.scheme in ("http", "https"):
        return bool(decoupe.netloc)
    return True


def detecter_provenance(ref: str) -> str | None:
    """`provenance_forgee` si `ref` non résolvable, sinon `None`."""
    return None if ref_resolvable(ref) else "provenance_forgee"


def contradiction_sans_preuve(croyance_etablie: bool, preuve_fournie: bool) -> bool:
    """Réfutation d'une croyance établie sans preuve : fardeau sur l'arrivant."""
    return bool(croyance_etablie and not preuve_fournie)


def saturation_atteinte(compte: int, plafond: int) -> bool:
    """Volume au-delà du plafond (budgets T1.5, `max_ingest_per_cycle`)."""
    return compte >= plafond


def analyser(texte: str, ref: str) -> list[str]:
    """Motifs du document, dans l'ordre (`[]` = propre) ; jamais levée."""
    try:
        motifs = []
        instruction = detecter_instruction(texte)
        if instruction is not None:
            motifs.append(instruction)
        provenance = detecter_provenance(ref)
        if provenance is not None:
            motifs.append(provenance)
        return motifs
    except Exception:  # noqa: BLE001 — détection best-effort, jamais bloquante
        _LOG.exception("détection contenu")
        return []
