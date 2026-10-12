# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T8.1/T8.2/T8.4 — pont sans FastAPI : mapping statuts, timeout, fabrique."""

from __future__ import annotations

from concurrent.futures import Future

from evidra.api.pont import ContexteAPI, executer, reponse
from evidra.kernel.contracts import Status, ToolResult
from evidra.kernel.scheduler import Priorite


def test_reponse_statuts() -> None:
    assert reponse(ToolResult(status=Status.OK, payload={"a": 1}))[0] == 200
    degrade = reponse(ToolResult(status=Status.DEGRADE, payload={}, warnings=("w",)))
    assert degrade[0] == 200 and degrade[1]["warnings"] == ["w"]
    assert reponse(ToolResult(status=Status.REFUSED, payload={}))[0] == 403
    assert reponse(ToolResult(status=Status.FAILED, payload={}))[0] == 500
    assert reponse(ToolResult(status=Status.FAILED, payload={"timeout": True}))[0] == 504


def test_timeout_504() -> None:
    import time

    class Lent:
        def run(self, ctx, args):
            time.sleep(5.0)
            return ToolResult(status=Status.OK, payload={})

    depoee = {}

    def deposer(_niveau: Priorite, effet) -> Future[ToolResult]:
        import threading

        futur: Future[ToolResult] = Future()
        depoee["lance"] = True

        def fond() -> None:
            try:
                if not futur.done():
                    futur.set_result(effet())
            except Exception:  # noqa: BLE001 — test
                pass

        threading.Thread(target=fond, daemon=True).start()
        return futur

    ctx = ContexteAPI(
        deposer=deposer,
        domaine="code",
        timeout_s=0.05,
        construire=lambda _nom: Lent(),  # type: ignore[return-value]
        extraire=None,
        lire_etat=lambda: {},
        lire_alertes=lambda: [],
        ctx_memoire=None,  # type: ignore[arg-type]
    )
    recu = executer(ctx, Priorite.P3, "query_causes", {"concept": "x"})
    assert depoee.get("lance") is True
    assert recu.status is Status.FAILED and recu.payload.get("timeout") is True
    assert reponse(recu)[0] == 504


def test_outil_inconnu_500() -> None:
    from evidra.kernel.contracts import Context as Ctx

    def deposer(_niveau: Priorite, effet) -> Future[ToolResult]:
        futur: Future[ToolResult] = Future()
        futur.set_result(effet())
        return futur

    ctx = ContexteAPI(
        deposer=deposer,
        domaine="code",
        timeout_s=5.0,
        construire=lambda _nom: None,
        extraire=None,
        lire_etat=lambda: {},
        lire_alertes=lambda: [],
        ctx_memoire=Ctx(store=None, domain="code"),  # type: ignore[arg-type]
    )
    recu = executer(ctx, Priorite.P3, "fantome", {})
    assert reponse(recu)[0] == 500
