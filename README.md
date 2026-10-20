# relay-agent

Client de [Relay](https://github.com/jStrider/relay) pour un agent IA. L'app Relay dépose sur un relais les données Apple Health de son utilisateur, chiffrées avec une clé qui ne quitte pas l'iPhone. Ce client les déchiffre avec la phrase d'appairage, les écrit en fichiers lisibles par l'agent, planifie les séances de course qui partent sur la montre, et demande un rafraîchissement à l'iPhone. Il existe en ligne de commande, en pont sans secret pour un agent en bac à sable, et en serveur MCP.

## Installation et appairage

```sh
pip install relay-agent            # ou : uv tool install relay-agent
mkdir -p ~/.config/relay && (umask 077; printf '%s' 'relay1:…' > ~/.config/relay/phrase)
export RELAY_URL=https://relay.<domaine>   # inutile avec le relais par défaut
```

La phrase `relay1:<id>:<jeton>:<cle>` s'affiche dans l'app, onglet Réglages, en texte et en QR. Elle donne accès à toutes les données : le client refuse un fichier lisible par d'autres utilisateurs. `RELAY_PHRASE` remplace le fichier.

## Relier un agent par code court (recommandé)

```sh
relay-agent relier
# Dans l'app Relay, « Relier un agent », saisis : K7Q2-M6XA
# Code à comparer avec celui de l'app : 327365
# Appairé : phrase enregistrée dans ~/.config/relay/phrase
```

L'agent et l'app échangent des clés éphémères par le relais, affichent le même code à six chiffres, et la phrase passe chiffrée dès que tu confirmes dans l'app. Le relais ne voit que du chiffré. `--oui` remplace une phrase déjà enregistrée. Depuis le pont : `POST /relier` renvoie la session, `GET /relier/<session>` donne l'état (`attente_app`, `code`, `appairé`, `expiré`) et le code.

## Ligne de commande

| Commande | Effet | Sortie |
|---|---|---|
| `relay-agent sync --dest D` | Tire et déchiffre les blobs modifiés, écrit `D/sante/metriques/<nom>.json`, `D/sante/seances/*.json`, `D/sante/etat.json`, `D/coach/prevu.json` | résumé sur stderr |
| `relay-agent resume --dest D [--sans-rafraichir]` | Demande une synchro fraîche à l'iPhone, synchronise, imprime le résumé santé daté | texte |
| `relay-agent rafraichir` | Réveille l'iPhone et attend sa synchro | `{"http": 200, "corps": {…}, "erreur": null}` |
| `relay-agent seance ajouter --id 2026-10-21-frac-6x3 --nom "Frac 6 × 3 min" --date 2026-10-21T18:30:00+02:00 --echauffement 600 --bloc "6x effort:180@4:25-4:40 recup:120" --retour-calme 600 --dest D` | Planifie une séance (local puis relais) | liste des séances |
| `relay-agent seance retirer <id>` · `lister` · `purger` | Retire, liste, retire les séances passées | liste des séances |
| `relay-agent pont --ecoute 172.17.0.1:8771 --dest D` | Pont HTTP sans secret pour un conteneur | journal sur stderr |
| `relay-agent mcp --dest D` | Serveur MCP sur stdio | |
| `relay-agent relier [--oui]` | Appairage par code court (voir plus haut) | session, code, confirmation |

Une étape de bloc est `effort:` ou `recup:` suivi d'une durée en secondes ou d'une distance (`400m`), avec `@allure` optionnelle en min/km (`4:25-4:40`) ou en s/km (`265-280`). Même `id` = la séance est remplacée.

Codes de sortie : 0 succès, 2 usage ou validation, 3 relais injoignable, 4 abonnement requis.

## Pont pour un agent en bac à sable

Le client tourne sur l'hôte avec la phrase ; le conteneur n'a ni phrase ni réseau sortant à ouvrir :

```sh
relay-agent pont --ecoute 172.17.0.1:8771 --dest /home/agent/workspace
```

Depuis le conteneur : `POST /sync`, `POST /rafraichir`, `POST /seance` avec `{"args": ["ajouter", "--id", …]}`, `GET /etat`. Le pont refuse d'écouter sur `0.0.0.0`.

## Serveur MCP

Claude Desktop (`claude_desktop_config.json`) ou Cursor (`.cursor/mcp.json`) :

```json
{"mcpServers": {"relay": {"command": "relay-agent", "args": ["mcp", "--dest", "/Users/moi/relay"]}}}
```

La phrase vient de `~/.config/relay/phrase` (mode 600) : ne la mets pas dans ce fichier de configuration, souvent lisible par d'autres. `RELAY_PHRASE` reste pour les conteneurs.

Outils : `etat`, `resume`, `metriques(nom, jours)`, `seances(jours)`, `planifier(id, nom, date, blocs, echauffement_s, retour_calme_s)`, `retirer(id)`, `rafraichir`.

## Développement

`uv sync`, `uv run pytest -q`. Le contrat de chiffrement est dans `vecteurs/chiffrement.json`, copie de celui publié par `relay-serveur`.
