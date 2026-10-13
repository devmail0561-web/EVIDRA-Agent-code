# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Application FastAPI (T8.1/T8.2/T8.4) : endpoints causaux sur le scheduler.

T8.3 greffera l'authentification (`api/auth.py`) via `autheur`.
"""

from __future__ import annotations

import threading
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from evidra.api.auth import Autheur, canonique
from evidra.api.pont import ContexteAPI, deposer_attendre, effet_ingest_textes, executer, reponse
from evidra.kernel.contracts import ToolResult, Verb
from evidra.kernel.scheduler import Priorite
from evidra.output.agent import formater_agent
from evidra.output.human import formater_humain
from evidra.output.llm import formater_llm

FormatSortie = Literal["llm", "human", "agent"]


class TextesIn(BaseModel):
    textes: list[str] = Field(min_length=1)
    canal: str = "api"


class ClaimIn(BaseModel):
    claim: str | dict[str, Any]


class DirectiveIn(BaseModel):
    directive: dict[str, Any]
    motif: str = ""
    signature: str = ""


class RollbackIn(BaseModel):
    motif: str = ""
    signature: str = ""


def mettre_en_forme(recu: ToolResult, format: str) -> Any:
    """Formateurs T5.7 (fil HTTP, pur, sans mémoire)."""
    if format == "human":
        return formater_humain(recu)
    if format == "agent":
        return formater_agent(recu)
    return formater_llm(recu)


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    secret = authorization[7:].strip()
    return secret or None


def exige(autheur: Autheur | None, *verbes: Verb):
    """Dépendance FastAPI : 401 sans jeton, 403 verbe insuffisant (T8.3)."""

    def dependance(authorization: str | None = Header(default=None)) -> str | None:
        if autheur is None:
            return None
        verdict = autheur.autorise(_bearer(authorization), verbes)
        if verdict == "anonyme":
            raise HTTPException(status_code=401, detail="jeton manquant ou inconnu")
        if verdict == "interdit":
            raise HTTPException(status_code=403, detail="verbe non autorisé")
        return _bearer(authorization)

    return dependance


def creer_app(
    boucle: Any,
    ctx: ContexteAPI,
    *,
    autheur: Autheur | None = None,
    directive_path: Any | None = None,
) -> FastAPI:
    """Fabrique l'app ; `lifespan` fait tourner la boucle (T8.1).

    `autheur=None` (aucun jeton) = routes ouvertes dev/dogfood (documenté) ;
    sinon 401 sans jeton, 403 verbe insuffisant (T8.3).
    """
    lecture = [Depends(exige(autheur, Verb.READ))]
    ecriture = [Depends(exige(autheur, Verb.INGEST))]
    gouvernance = [Depends(exige(autheur, Verb.MODIFY))]

    @asynccontextmanager
    async def duree_vie(app: FastAPI):
        arret = threading.Event()
        fil = threading.Thread(target=boucle.boucler, args=(arret,), daemon=True)
        fil.start()
        app.state.arret = arret
        try:
            yield
        finally:
            arret.set()
            fil.join(timeout=ctx.timeout_s)

    app = FastAPI(title="Evidra", version="1.0", lifespan=duree_vie)
    app.state.ctx = ctx
    app.state.boucle = boucle

    def repondre(recu: ToolResult, format: FormatSortie = "llm") -> JSONResponse:
        code, corps = reponse(recu)
        if recu.status.value in ("ok", "degrade"):
            corps["format"] = format
            corps["donnees"] = mettre_en_forme(recu, format)
        return JSONResponse(corps, status_code=code)

    @app.post("/analyze", dependencies=lecture)
    def analyser(entree: TextesIn) -> JSONResponse:
        if ctx.extraire is None:
            return JSONResponse({"erreur": "moteur indisponible (B2)"}, status_code=503)
        recu = deposer_attendre(ctx, Priorite.P3, lambda: ctx.extraire(entree.textes))
        code, corps = reponse(recu)
        return JSONResponse(corps, status_code=code)

    @app.post("/ingest", dependencies=ecriture)
    def ingerer(entree: TextesIn) -> JSONResponse:
        if ctx.extraire is None:
            return JSONResponse({"erreur": "moteur indisponible (B2)"}, status_code=503)
        recu = effet_ingest_textes(ctx, "ingest", entree.textes, entree.canal)
        code, corps = reponse(recu)
        return JSONResponse(corps, status_code=code)

    @app.get("/query/causes/{concept}", dependencies=lecture)
    def causes(
        concept: str,
        domaine: str = "",
        format: FormatSortie = "llm",
    ) -> JSONResponse:
        return repondre(
            executer(
                ctx, Priorite.P3, "query_causes", {"concept": concept}, domaine=domaine or None
            ),
            format,
        )

    @app.get("/query/effects/{concept}", dependencies=lecture)
    def effets(
        concept: str,
        domaine: str = "",
        format: FormatSortie = "llm",
    ) -> JSONResponse:
        return repondre(
            executer(
                ctx, Priorite.P3, "query_effects", {"concept": concept}, domaine=domaine or None
            ),
            format,
        )

    @app.get("/query/chain/{de}/{vers}", dependencies=lecture)
    def chaine(
        de: str,
        vers: str,
        domaine: str = "",
        format: FormatSortie = "llm",
    ) -> JSONResponse:
        return repondre(
            executer(
                ctx, Priorite.P3, "query_chain", {"de": de, "vers": vers}, domaine=domaine or None
            ),
            format,
        )

    @app.post("/validate", dependencies=lecture)
    def valider(entree: ClaimIn, format: FormatSortie = "llm") -> JSONResponse:
        return repondre(executer(ctx, Priorite.P2, "validate", {"claim": entree.claim}), format)

    @app.get("/status", dependencies=lecture)
    def statut() -> JSONResponse:
        recu = deposer_attendre(ctx, Priorite.P3, lambda: _etat_outil(ctx))
        code, corps = reponse(recu)
        return JSONResponse(corps, status_code=code)

    @app.get("/alerts", dependencies=lecture)
    def alertes() -> JSONResponse:
        recu = deposer_attendre(ctx, Priorite.P3, lambda: _alertes_outil(ctx))
        code, corps = reponse(recu)
        return JSONResponse(corps, status_code=code)

    if directive_path is not None:
        _routes_directive(app, ctx, autheur, directive_path, gouvernance)

    return app


def _etat_outil(ctx: ContexteAPI) -> ToolResult:
    from evidra.kernel.contracts import Status

    try:
        return ToolResult(status=Status.OK, payload={"etat": dict(ctx.lire_etat())})
    except Exception as exc:  # noqa: BLE001 — jamais levée vers HTTP
        return ToolResult(status=Status.FAILED, payload={"motif": f"panne : {exc}"})


def _alertes_outil(ctx: ContexteAPI) -> ToolResult:
    from evidra.kernel.contracts import Status

    try:
        return ToolResult(status=Status.OK, payload={"alertes": list(ctx.lire_alertes())})
    except Exception as exc:  # noqa: BLE001 — jamais levée vers HTTP
        return ToolResult(status=Status.FAILED, payload={"motif": f"panne : {exc}"})


def _routes_directive(
    app: FastAPI,
    ctx: ContexteAPI,
    autheur: Autheur | None,
    directive_path: Any,
    gouvernance: list[Any],
) -> None:
    """POST /directive + rollback (T8.3) : verbe `modify` + signature HMAC, WAL tracé."""
    import hashlib
    import json as _json
    import logging
    import os
    from pathlib import Path

    from evidra.directive.schema import valider

    log = logging.getLogger(__name__)
    chemin = Path(directive_path)
    app.state.directive_precedente = chemin.read_bytes() if chemin.exists() else b""

    def _ecrire(contenu: bytes) -> None:
        tmp = chemin.with_suffix(".json.tmp")
        with open(tmp, "wb") as flux:
            flux.write(contenu)
            flux.flush()
            os.fsync(flux.fileno())
        tmp.replace(chemin)

    def _tracer(auteur: str, motif: str, hachage: str) -> None:
        recu = deposer_attendre(
            ctx, Priorite.P3, lambda: _append_version(ctx, auteur, motif, hachage)
        )
        if recu.status.value != "ok":
            log.warning("version directive non tracée : %s", recu.payload.get("motif"))

    def _auteur(authorization: str | None) -> str:
        secret = _secret(authorization)
        nom = autheur.nom_jeton(secret) if autheur is not None and secret else None
        return nom or "api"

    @app.post("/directive", dependencies=gouvernance)
    def publier(
        entree: DirectiveIn,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if autheur is not None:
            if not entree.signature or ":" not in entree.signature:
                return JSONResponse({"erreur": "signature directive invalide"}, status_code=403)
            cle_id, sig = entree.signature.split(":", 1)
            if not autheur.verifier_signature(cle_id, canonique(entree.directive), sig):
                return JSONResponse({"erreur": "signature directive invalide"}, status_code=403)
        try:
            valider(entree.directive)
        except Exception as exc:  # noqa: BLE001 — fail-closed avant écriture
            return JSONResponse({"erreur": f"directive invalide : {exc}"}, status_code=422)
        nouveau = _json.dumps(entree.directive, sort_keys=True, ensure_ascii=False).encode("utf-8")
        app.state.directive_precedente = chemin.read_bytes() if chemin.exists() else b""
        _ecrire(nouveau)
        _tracer(_auteur(authorization), entree.motif, hashlib.sha256(nouveau).hexdigest())
        return JSONResponse({"publiee": True}, status_code=200)

    @app.post("/directive/rollback", dependencies=gouvernance)
    def retour(
        entree: RollbackIn,
        authorization: str | None = Header(default=None),
    ) -> JSONResponse:
        if autheur is not None:
            if not entree.signature or ":" not in entree.signature:
                return JSONResponse({"erreur": "signature directive invalide"}, status_code=403)
            cle_id, sig = entree.signature.split(":", 1)
            corps = canonique({"rollback": True, "motif": entree.motif})
            if not autheur.verifier_signature(cle_id, corps, sig):
                return JSONResponse({"erreur": "signature directive invalide"}, status_code=403)
        precedent = app.state.directive_precedente
        if not precedent:
            return JSONResponse({"erreur": "aucune version précédente"}, status_code=409)
        _ecrire(precedent)
        _tracer(_auteur(authorization), f"rollback : {entree.motif}", "rollback")
        return JSONResponse({"restauree": True}, status_code=200)


def _secret(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    return authorization[7:].strip() or None


def _append_version(ctx: ContexteAPI, auteur: str, motif: str, hachage: str) -> ToolResult:
    from evidra.kernel.contracts import Record, Status

    try:
        seq = ctx.ctx_memoire.store.append(
            "registry/directive",
            Record(
                stream="registry/directive",
                op="version",
                key=f"v:{hachage[:12]}",
                data={"auteur": auteur, "motif": motif, "hash": hachage},
            ),
        )
        return ToolResult(status=Status.OK, payload={"seq": seq})
    except Exception as exc:  # noqa: BLE001 — jamais levée vers HTTP
        return ToolResult(status=Status.FAILED, payload={"motif": f"panne : {exc}"})
