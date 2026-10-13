# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""Adaptateur `http_feed` (T9.8) : flux RSS/Atom → `RawDoc`, dégradé offline.

`poll(since)` fait un GET conditionnel (`ETag`/`If-Modified-Since`) par URL
via `httpx` exécuté en worker (`engine_bridge.travailleur.lancer`, repli
`timeout` httpx direct si le pont est indisponible) avec le `timeout_s`
injecté au constructeur (jamais de lecture directive ici). Chaque entrée
`feedparser` devient un `RawDoc` (`uri=url#id`, texte=titre+résumé,
`channel="http_feed"`, `published_at` si dispo — ref URL résolvable).

Robustesse : échec réseau/HTTP/parse ⇒ URL ignorée et comptée
(`compteurs`, journal `warning` = motif dégradé), jamais levée — hors ligne
⇒ `[]` dégradé, coupure en cours de cycle ⇒ le cycle continue sur les URLs
suivantes. `304 Non Modifié` ⇒ rien. Backoff exponentiel par URL (plafond
5 min) évite de marteler un flux en panne. Curseur opaque JSON
`{vus:[...]}` (URIs déjà rendues), validé fail-fast par `ack()`.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import feedparser
import httpx

from evidra.kernel.contracts import CostHint, Cursor, RawDoc

try:  # pont worker dispo ⇒ timeout directive appliqué hors scheduler
    from evidra.engine_bridge.travailleur import WorkerTimeout
    from evidra.engine_bridge.travailleur import lancer as _lancer_worker
except ImportError:  # moteur absent : repli timeout httpx direct
    WorkerTimeout = TimeoutError  # type: ignore[assignment,misc]
    _lancer_worker = None  # type: ignore[assignment]

log = logging.getLogger("evidra.adapters.http_feed")

_BACKOFF_PLAFOND_S = 300.0


def _delai_backoff(echecs: int) -> float:
    return min(_BACKOFF_PLAFOND_S, 2.0 ** min(max(echecs, 1), 8))


def _texte_entree(entree: Mapping[str, Any]) -> str:
    titre = str(entree.get("title") or "").strip()
    resume = str(entree.get("summary") or entree.get("description") or "").strip()
    if titre and resume:
        return f"{titre}\n{resume}"
    return titre or resume or str(entree.get("link") or "").strip()


def _date_entree(entree: Mapping[str, Any]) -> str | None:
    for cle in ("published", "updated", "pubDate"):
        valeur = entree.get(cle)
        if isinstance(valeur, str) and valeur.strip():
            return valeur.strip()
    return None


class AdaptateurFlux:
    """Adapte des flux RSS/Atom distants au contrat `Adapter` (pull HTTP)."""

    name = "http_feed"
    version = "0.1.0"
    harness_required = "1.0"
    input_schema: Mapping[str, Any] = {
        "type": "object",
        "properties": {"since": {"type": ["string", "null"]}},
    }
    output_schema: Mapping[str, Any] = {"type": "object", "properties": {"docs": {"type": "array"}}}
    cost_hint = CostHint(ms=500.0, calls=1)
    permissions: frozenset = frozenset()  # réseau via httpx, pas de verbe harness
    channels: tuple[str, ...] = ("http_feed",)
    requires_network = True

    def __init__(
        self,
        urls: Sequence[str] | None = None,
        *,
        timeout_s: float = 5.0,
        canal: str = "http_feed",
        etag_store: MutableMapping[str, Any] | None = None,
    ) -> None:
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or float(timeout_s) <= 0
        ):
            raise ValueError(f"timeout invalide : {timeout_s!r}")
        if urls is None:
            validees: tuple[str, ...] = ()
        elif isinstance(urls, (str, bytes)) or not isinstance(urls, Sequence):
            raise ValueError("urls : séquence de chaînes exigée")
        else:
            validees = tuple(urls)
            for url in validees:
                if (
                    not isinstance(url, str)
                    or not url.strip()
                    or not url.startswith(("http://", "https://"))
                ):
                    raise ValueError(f"url invalide : {url!r}")
        self._urls = validees
        self._timeout_s = float(timeout_s)
        self.canal = canal
        self._cache: MutableMapping[str, Any] = etag_store if etag_store is not None else {}
        self._etat: set[str] = set()
        self._echecs: dict[str, int] = {}
        self._prochain_essai: dict[str, float] = {}
        self.compteurs: dict[str, int] = {}
        self._dernier_ack: str | None = None

    def poll(self, since: Cursor | None) -> list[RawDoc]:
        """GET conditionnel par URL → `RawDoc` ; échec ⇒ ignoré compté, jamais levé."""
        vus = self._charger_curseur(since)
        trouves: list[RawDoc] = []
        for url in self._urls:
            if time.monotonic() < self._prochain_essai.get(url, 0.0):
                log.debug("backoff : flux sauté", extra={"url": url})
                continue
            try:
                reponse = self._telecharger(url)
            except Exception as exc:  # réseau/timeout worker : dégradé, cycle continue
                self._compter("reseau")
                self._armer_backoff(url)
                log.warning("flux dégradé (réseau)", extra={"url": url, "motif": str(exc)})
                continue
            if reponse.status_code == 304:  # noqa: PLR2004 — code HTTP canonique
                self._echecs.pop(url, None)
                continue
            if reponse.status_code >= 400:  # noqa: PLR2004 — codes HTTP canoniques
                self._compter(f"http_{reponse.status_code}")
                self._armer_backoff(url)
                log.warning(
                    "flux dégradé (http)", extra={"url": url, "statut": reponse.status_code}
                )
                continue
            self._memoriser_cache(url, reponse)
            try:
                flux = feedparser.parse(reponse.content)
            except Exception as exc:
                self._compter("parse")
                log.warning("flux dégradé (parse)", extra={"url": url, "motif": str(exc)})
                continue
            entrees = getattr(flux, "entries", None) or []
            if getattr(flux, "bozo", 0) and not entrees:
                self._compter("parse")
                log.warning("flux dégradé (parse)", extra={"url": url, "motif": "bozo"})
                continue
            for rang, entree in enumerate(entrees):
                try:
                    doc = self._doc_entree(url, dict(entree), rang)
                except Exception as exc:
                    self._compter("entree")
                    log.warning("entrée ignorée", extra={"url": url, "motif": str(exc)})
                    continue
                if doc.uri in vus:
                    continue
                vus.add(doc.uri)
                trouves.append(doc)
            self._echecs.pop(url, None)
        self._etat = set(vus)
        return trouves

    def ack(self, curseur: str) -> None:
        """Marque un curseur (validé, fail-fast) ; la persistance relève de l'appelant."""
        try:
            objet = json.loads(curseur)
        except ValueError:
            raise ValueError("curseur illisible") from None
        if (
            not isinstance(objet, dict)
            or not isinstance(objet.get("vus"), list)
            or not all(isinstance(x, str) for x in objet["vus"])
        ):
            raise ValueError("curseur mal formé")
        self._dernier_ack = curseur

    def curseur(self) -> str:
        """État courant sérialisé (à persister via les registres, T2.6)."""
        return json.dumps({"vus": sorted(self._etat)}, sort_keys=True)

    def _telecharger(self, url: str) -> httpx.Response:
        headers: dict[str, str] = {}
        cached = self._cache.get(url)
        if isinstance(cached, Mapping):
            etag = cached.get("etag")
            if isinstance(etag, str) and etag:
                headers["If-None-Match"] = etag
            modifie = cached.get("last_modified")
            if isinstance(modifie, str) and modifie:
                headers["If-Modified-Since"] = modifie

        def _get() -> httpx.Response:
            return httpx.get(url, headers=headers, timeout=self._timeout_s, follow_redirects=True)

        if _lancer_worker is not None:
            return _lancer_worker(_get, self._timeout_s)
        return _get()

    def _memoriser_cache(self, url: str, reponse: httpx.Response) -> None:
        try:
            headers = reponse.headers
            etag = headers.get("etag") if hasattr(headers, "get") else None
            modifie = headers.get("last-modified") if hasattr(headers, "get") else None
            if etag or modifie:
                self._cache[url] = {"etag": etag, "last_modified": modifie}
        except (ValueError, TypeError, AttributeError):
            log.debug("cache etag ignoré", extra={"url": url})

    def _doc_entree(self, url: str, entree: dict[str, Any], rang: int) -> RawDoc:
        ident = (
            str(entree.get("id") or "").strip()
            or str(entree.get("link") or "").strip()
            or str(entree.get("title") or "").strip()
            or f"entree-{rang}"
        )
        return RawDoc(
            uri=f"{url}#{ident}",
            text=_texte_entree(entree),
            channel=self.canal,
            mime="text/plain",
            published_at=_date_entree(entree),
        )

    def _charger_curseur(self, curseur: str | None) -> set[str]:
        if curseur is None:
            return set()
        try:
            objet = json.loads(str(curseur))
        except ValueError:
            log.warning("curseur illisible : re-scan complet (idempotent)")
            return set()
        vus = objet.get("vus") if isinstance(objet, dict) else None
        if not isinstance(vus, list):
            return set()
        return {x for x in vus if isinstance(x, str)}

    def _compter(self, motif: str) -> None:
        self.compteurs[motif] = self.compteurs.get(motif, 0) + 1

    def _armer_backoff(self, url: str) -> None:
        echecs = self._echecs.get(url, 0) + 1
        self._echecs[url] = echecs
        self._prochain_essai[url] = time.monotonic() + _delai_backoff(echecs)
