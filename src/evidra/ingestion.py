# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Pipeline F1 partagé (T3.8, absorbé par le scheduler en T4.4) : un document.

`poll → phrases → extract → enveloppement (ancre document) → ingest`.
L'ordonnancement (politique, boucle, budgets) relève de T4.x ; ici seule la
plomberie bout-en-bout, avec dépendances explicites injectées.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any, Protocol

from evidra.engine_bridge.extract import extraire
from evidra.engine_bridge.moteur import Moteur
from evidra.engine_bridge.provenance import envelopper, verifier, vers_noyaux
from evidra.kernel.contracts import Adapter, Context, Tool
from evidra.memory.envelope import Span
from evidra.security.content import analyser as analyser_contenu

_SEPARATEUR = re.compile(r"[.!?…\n]+", re.UNICODE)

Detecteur = Callable[[str, str], str | None]
"""Document (texte, ref) → motif de quarantaine ou `None` (T9.4/T9.5)."""


def detecteur_defaut(texte: str, ref: str) -> str | None:
    """Injonctions + ref non résolvable (ne voit jamais le moteur)."""
    motifs = analyser_contenu(texte, ref)
    return motifs[0] if motifs else None


_LOG = logging.getLogger(__name__)


class SourceLocale(Adapter, Protocol):
    """Adaptateur capable d'ancrer un document (span réel, T3.2)."""

    canal: str

    def etendue(self, texte: str, *, code: bool = False, fichier: str = "") -> Span:
        """Ancre couvrant le document (TokenSpan texte, CodeSpan code)."""
        ...


def decouper_phrases(texte: str) -> list[str]:
    """Segmentation naïve (stdlib) : une phrase = segment non vide."""
    return [s.strip() for s in _SEPARATEUR.split(texte) if s and s.strip()]


def traiter_document(
    *,
    adaptateur: SourceLocale,
    moteur: Moteur | None,
    outil: Tool,
    ctx: Context,
    uri: str,
    texte: str,
    code: bool = False,
    fichier: str = "",
    timeout_s: float | None = None,
    detecteur: Detecteur | None = None,
) -> dict[str, Any]:
    """Ingère un document : stats par étape, jamais levée (comptée).

    La porte `can()` est appliquée par l'outil (`OutilIngest.run` → `refused`
    sans effet) ; ici seule la plomberie F1. `timeout_s=None` ⇒ défaut directive (I9).
    `detecteur=None` ⇒ `detecteur_defaut` (T9.4) ; motif non nul ⇒ `quarantaine`
    posée à l'ingest (T9.5, stockée, exclue des requêtes/CONFIRMED).
    """
    from evidra.directive.schema import timeout_travailleur_defaut

    delai = timeout_travailleur_defaut() if timeout_s is None else timeout_s
    sonde = detecteur if detecteur is not None else detecteur_defaut
    stats: dict[str, Any] = {
        "phrases": 0,
        "cirs": 0,
        "inverifiables": 0,
        "invalides": 0,
        "ajoutees": 0,
        "confirmees": 0,
        "idempotentes": 0,
        "quarantaine": None,
        "dropped": {},
    }
    try:
        try:
            motif_quarantaine = sonde(texte, uri)
        except Exception:  # noqa: BLE001 — détection best-effort, jamais bloquante
            _LOG.exception("détection contenu %s", uri)
            motif_quarantaine = None
        if not isinstance(motif_quarantaine, str) or not motif_quarantaine.strip():
            motif_quarantaine = None
        stats["quarantaine"] = motif_quarantaine
        phrases = decouper_phrases(texte)
        stats["phrases"] = len(phrases)
        if not phrases:
            return stats
        recu_ext = extraire(phrases, moteur=moteur, timeout_s=delai)
        if recu_ext.payload.get("cirs") is None:
            stats["invalides"] += 1
            return stats
        cirs = recu_ext.payload["cirs"]
        stats["cirs"] = len(cirs)
        ancre = adaptateur.etendue(texte, code=code, fichier=fichier)
        noyaux = []
        for cir in cirs:
            try:
                marqueurs = {
                    e[2].get("marker_token")
                    for e in cir.get("edges", [])
                    if isinstance(e, (list, tuple)) and len(e) == 3 and isinstance(e[2], dict)
                }
                spans = {m: ancre for m in marqueurs if m is not None}
                enrichi = envelopper(cir, ref=uri, texte=texte, spans=spans or None)
            except (ValueError, KeyError, TypeError):
                stats["invalides"] += 1
                continue
            if not verifier(enrichi, texte):
                stats["inverifiables"] += 1
                continue
            try:
                noyaux.extend(vers_noyaux(enrichi))
            except ValueError:
                stats["invalides"] += 1
        if not noyaux:
            return stats
        args_ingest: dict[str, Any] = {"noyaux": noyaux, "channel": adaptateur.canal}
        if motif_quarantaine is not None:
            args_ingest["quarantaine"] = motif_quarantaine
        recu = outil.run(ctx, args_ingest)
        for cle in ("ajoutees", "confirmees", "idempotentes"):
            stats[cle] = int(recu.payload.get(cle, 0))
        for motif, n in dict(recu.payload.get("dropped", {})).items():
            stats["dropped"][motif] = stats["dropped"].get(motif, 0) + int(n)
        stats["trace_ref"] = recu.payload.get("trace_ref")
        return stats
    except Exception as exc:  # noqa: BLE001 — un document n'arrête jamais le flux
        _LOG.exception("document iningérable %s", uri)
        stats["invalides"] += 1
        stats["erreur"] = str(exc)
        return stats
