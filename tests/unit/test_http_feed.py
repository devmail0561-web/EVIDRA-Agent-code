# Copyright 2026 Michel Tendeng
# SPDX-License-Identifier: Apache-2.0
"""T9.8 — http_feed : construction, poll dégradé, parse RSS, curseur, timeout."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

httpx = pytest.importorskip("httpx")
pytest.importorskip("feedparser")

from evidra.adapters import http_feed  # noqa: E402
from evidra.adapters.http_feed import AdaptateurFlux  # noqa: E402
from evidra.kernel.contracts import Adapter, RawDoc  # noqa: E402
from evidra.kernel.manifest import manifest_from_plugin  # noqa: E402

URL = "http://example.com/flux.xml"

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>T</title><link>http://example.com</link>
<item><guid>1</guid><title>Premier</title><description>Resume un</description>
<pubDate>Mon, 01 Jan 2026 00:00:00 +0000</pubDate><link>http://example.com/1</link></item>
<item><guid>2</guid><title>Second</title><description>Resume deux</description>
<link>http://example.com/2</link></item>
</channel></rss>"""


def _reponse(
    contenu: bytes = RSS, statut: int = 200, headers: dict[str, str] | None = None
) -> SimpleNamespace:
    return SimpleNamespace(status_code=statut, headers=headers or {}, content=contenu)


def test_construction_conforme() -> None:
    adaptateur = AdaptateurFlux([URL], timeout_s=2.0)
    assert isinstance(adaptateur, Adapter)
    assert adaptateur.requires_network is True
    assert adaptateur.name == "http_feed"
    assert adaptateur.canal == "http_feed"
    assert AdaptateurFlux([]).poll(None) == []  # poll vide
    assert manifest_from_plugin(AdaptateurFlux).name == "http_feed"
    assert manifest_from_plugin(AdaptateurFlux).requires_network is True


@pytest.mark.parametrize("mauvais", [0, -1.0, float("nan"), float("inf"), "5", True])
def test_timeout_invalide_refuse(mauvais: Any) -> None:
    with pytest.raises(ValueError):
        AdaptateurFlux([URL], timeout_s=mauvais)


def test_timeout_none_egale_defaut_directive() -> None:
    from evidra.directive.schema import backoff_plafond_defaut, timeout_http_defaut

    assert AdaptateurFlux([URL])._timeout_s == timeout_http_defaut()
    assert AdaptateurFlux([URL], timeout_s=None)._timeout_s == timeout_http_defaut()
    assert AdaptateurFlux([URL])._plafond_backoff == backoff_plafond_defaut()


@pytest.mark.parametrize("mauvais", [0, -2.0, float("nan"), "300", True])
def test_plafond_backoff_invalide_refuse(mauvais: Any) -> None:
    with pytest.raises(ValueError):
        AdaptateurFlux([URL], backoff_plafond_s=mauvais)


@pytest.mark.parametrize("mauvaises", [[""], ["ftp://x"], "http://x", [123]])
def test_url_invalide_refusee(mauvaises: Any) -> None:
    with pytest.raises(ValueError):
        AdaptateurFlux(mauvaises)


def test_poll_sans_reseau_degrade_jamais_leve(monkeypatch: pytest.MonkeyPatch) -> None:
    def _panne(url: str, **_kwargs: Any) -> Any:
        raise httpx.ConnectError("coupure")

    monkeypatch.setattr(httpx, "get", _panne)
    adaptateur = AdaptateurFlux([URL], timeout_s=1.0)
    assert adaptateur.poll(None) == []  # hors ligne ⇒ dégradé, jamais crash
    assert adaptateur.compteurs.get("reseau") == 1


def test_parse_flux_factice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, **_kw: _reponse())
    docs = AdaptateurFlux([URL], timeout_s=1.0).poll(None)
    assert len(docs) == 2
    assert all(isinstance(d, RawDoc) for d in docs)
    premier = next(d for d in docs if d.uri.endswith("#1"))
    assert premier.channel == "http_feed"
    assert "Premier" in premier.text and "Resume un" in premier.text
    assert premier.published_at  # date source, pas date d'ingestion
    assert all(d.uri.startswith(URL + "#") for d in docs)  # ref URL résolvable


def test_coupure_en_cours_de_cycle_continue(monkeypatch: pytest.MonkeyPatch) -> None:
    autre = "http://example.com/autre.xml"

    def _mixte(url: str, **_kwargs: Any) -> Any:
        if url == URL:
            raise httpx.ConnectError("coupure")
        return _reponse()

    monkeypatch.setattr(httpx, "get", _mixte)
    adaptateur = AdaptateurFlux([URL, autre], timeout_s=1.0)
    docs = adaptateur.poll(None)
    assert len(docs) == 2  # le cycle continue malgré la coupure sur URL
    assert adaptateur.compteurs.get("reseau") == 1


def test_worker_timeout_degrade(monkeypatch: pytest.MonkeyPatch) -> None:
    def _lent(_fn: Any, _delai: float) -> Any:
        raise http_feed.WorkerTimeout("worker dépassé")

    monkeypatch.setattr(http_feed, "_lancer_worker", _lent)
    assert AdaptateurFlux([URL], timeout_s=1.0).poll(None) == []


def test_etag_conditionnel_et_304(monkeypatch: pytest.MonkeyPatch) -> None:
    vus_headers: list[dict[str, str]] = []

    def _serveur(url: str, **kwargs: Any) -> Any:
        vus_headers.append(dict(kwargs.get("headers") or {}))
        if "If-None-Match" in vus_headers[-1]:
            return _reponse(b"", statut=304)
        return _reponse(headers={"etag": '"abc"', "last-modified": "Mon, 01 Jan 2026 00:00:00 GMT"})

    monkeypatch.setattr(httpx, "get", _serveur)
    magasin: dict[str, Any] = {}
    adaptateur = AdaptateurFlux([URL], timeout_s=1.0, etag_store=magasin)
    assert len(adaptateur.poll(None)) == 2
    assert magasin[URL]["etag"] == '"abc"'
    assert adaptateur.poll(adaptateur.curseur()) == []  # 304 ⇒ rien
    assert vus_headers[-1].get("If-None-Match") == '"abc"'
    assert vus_headers[-1].get("If-Modified-Since") == "Mon, 01 Jan 2026 00:00:00 GMT"


def test_curseur_ack_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, **_kw: _reponse())
    premier = AdaptateurFlux([URL], timeout_s=1.0)
    assert len(premier.poll(None)) == 2
    curseur = premier.curseur()
    vus = json.loads(curseur)["vus"]
    assert len(vus) == 2 and all(u.startswith(URL + "#") for u in vus)
    premier.ack(curseur)
    second = AdaptateurFlux([URL], timeout_s=1.0)
    assert second.poll(curseur) == []  # reprise sans retraitement
    assert AdaptateurFlux([URL], timeout_s=1.0).poll("corrompu{") != []  # illisible ⇒ re-scan
    with pytest.raises(ValueError):
        premier.ack("pas-du-json")
    with pytest.raises(ValueError):
        premier.ack(json.dumps({"vus": "non-liste"}))


def test_parse_corrompu_ignore_compte(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(httpx, "get", lambda url, **_kw: _reponse(b"\xff\xfe pas du xml {{{"))
    adaptateur = AdaptateurFlux([URL], timeout_s=1.0)
    assert adaptateur.poll(None) == []
    assert adaptateur.compteurs.get("parse") == 1


def test_hote_hors_liste_blanche_refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    def _jamais(url: str, **_kw: Any) -> Any:
        raise AssertionError(f"httpx.get ne doit pas être appelé : {url}")

    monkeypatch.setattr(httpx, "get", _jamais)
    adaptateur = AdaptateurFlux([URL], timeout_s=1.0, egress_hotes=["autre.example.com"])
    assert adaptateur.poll(None) == []
    assert adaptateur.compteurs.get("egress_refuse") == 1
