# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T1.6 — logging : ligne JSON par reçu, hiérarchie d'erreurs."""

from __future__ import annotations

import io
import json
import logging

from evidra.kernel.contracts import Cost, Status, ToolResult
from evidra.logging import (
    BudgetExceeded,
    ContractError,
    DirectiveError,
    EvidraError,
    JsonFormatter,
    PermissionDenied,
    configurer,
    log_recu,
)


def test_hierarchie_erreurs():
    assert issubclass(ContractError, EvidraError)
    assert issubclass(BudgetExceeded, EvidraError)
    assert issubclass(PermissionDenied, EvidraError)
    assert issubclass(DirectiveError, EvidraError)


def test_recu_produit_ligne_structuree():
    journal = logging.getLogger("evidra-test-recu")
    journal.setLevel(logging.INFO)
    flux = io.StringIO()
    main = logging.StreamHandler(flux)
    main.setFormatter(JsonFormatter())
    journal.handlers.clear()
    journal.addHandler(main)
    journal.propagate = False
    resultat = ToolResult(status=Status.DEGRADE, payload={}, cost=Cost(ms=3.0, calls=2))
    log_recu(journal, tick=7, outil="outil-factice", resultat=resultat)
    ligne = json.loads(flux.getvalue().strip())
    assert ligne["tick"] == 7
    assert ligne["outil"] == "outil-factice"
    assert ligne["status"] == "degrade"
    assert ligne["ms"] == 3.0
    assert ligne["calls"] == 2


def test_configurer_sans_doublon():
    premier = configurer()
    assert configurer() is premier
    assert len(premier.handlers) == 1
