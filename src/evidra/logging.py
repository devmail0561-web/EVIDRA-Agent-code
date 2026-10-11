# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Journalisation structurée et erreurs SA (T1.6, hors noyau).

Formateur JSON maison (~30 lignes) : chaque reçu produit une ligne avec
`tick`, `outil`, `status`, `cost` (acceptation T1.6). Hiérarchie
`EvidraError` → `ContractError`, `BudgetExceeded`, `PermissionDenied`,
`DirectiveError`.

Note : `ManifestError`/`RegistryError` (noyau) précèdent cette hiérarchie et
restent des `ValueError` — unification éventuelle en phase ultérieure, sans
impacter le budget SLOC du noyau (I2).
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

from evidra.kernel.contracts import ToolResult


class EvidraError(Exception):
    """Racine des erreurs SA."""


class ContractError(EvidraError):
    """Plugin hors contrat (isolé, puis quarantaine après 3 échecs)."""


class BudgetExceeded(EvidraError):  # noqa: N818 — nom imposé par T1.6
    """Budget de cycle dépassé (tracé `budget:`, jamais silencieux)."""


class PermissionDenied(EvidraError):  # noqa: N818 — nom imposé par T1.6
    """Refus de la porte `can()` remonté en erreur (le reçu reste `refused`)."""


class DirectiveError(EvidraError):
    """Directive invalide (rejetée, ancienne conservée — ADR-0008)."""


_RESERVES = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "message",
    }
)


class JsonFormatter(logging.Formatter):
    """Une ligne JSON par record : `ts`, niveau, message + champs `extra`."""

    def format(self, record: logging.LogRecord) -> str:
        ligne: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "niveau": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for cle, valeur in record.__dict__.items():
            if cle not in _RESERVES:
                ligne[cle] = valeur
        return json.dumps(ligne, ensure_ascii=False, default=str)


def configurer(niveau: int = logging.INFO) -> logging.Logger:
    """Logger `evidra` sur stderr, sans doublon de handler."""
    journal = logging.getLogger("evidra")
    journal.setLevel(niveau)
    if not journal.handlers:
        main = logging.StreamHandler(sys.stderr)
        main.setFormatter(JsonFormatter())
        journal.addHandler(main)
    return journal


def log_recu(journal: logging.Logger, *, tick: int, outil: str, resultat: ToolResult) -> None:
    """Une ligne structurée par reçu : tick, outil, status, coût."""
    journal.info(
        "recu",
        extra={
            "tick": tick,
            "outil": outil,
            "status": resultat.status.value,
            "ms": resultat.cost.ms,
            "calls": resultat.cost.calls,
            "trace_ref": resultat.trace_ref,
            "avertissements": list(resultat.warnings),
        },
    )
