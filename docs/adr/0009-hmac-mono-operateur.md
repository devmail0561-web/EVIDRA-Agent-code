# ADR-0009 — HMAC mono-opérateur, Ed25519 au 2e opérateur

- Date : 2026-10-11
- Statut : accepté
- Fonde : ETUDE_SA.md §17.2 / PLAN_SA.md §3.4 (T9.2)

## Contexte

Cas actuel : owner solo. Les CIR inter-agents doivent être signés (rejet
fail-closed sinon), avec anti-rejeu (`nonce`, `ts`, fenêtre 5 min) et rotation
documentée.

## Décision

HMAC-SHA256, une clé par agent (jamais partagée), stockage fichier 0600 +
env. Passage à Ed25519 (clés publiques dans `trusted_agents`) au 2e
opérateur — pas avant.

## Conséquences

Enveloppe `signature: {algo, key_id, nonce, ts}` ; rotation = remplacement +
reclassement `EN RÉVISION` depuis la date supposée.

## Alternative rejetée

Ed25519 d'emblée — sur-ingénierie pour un déploiement mono-opérateur.
