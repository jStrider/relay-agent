# relay-agent

[English](https://github.com/jStrider/relay-agent/blob/main/README.md) · Français

Client de [Relay](https://github.com/jStrider/relay) pour un agent IA. L'app Relay dépose sur un relais les données Apple Health de son utilisateur, chiffrées avec une clé qui ne quitte pas l'iPhone. Ce client les déchiffre avec la phrase d'appairage, les écrit en fichiers lisibles par l'agent, planifie les séances de course qui partent sur la montre, et demande un rafraîchissement à l'iPhone. Il existe en ligne de commande, en pont sans secret pour un agent en bac à sable, et en serveur MCP.

## Installation et appairage

```sh
uv tool install git+https://github.com/jStrider/relay-agent   # ou : pipx install git+https://github.com/jStrider/relay-agent
mkdir -p ~/.config/relay && (umask 077; printf '%s' 'relay1:…' > ~/.config/relay/phrase)
export RELAY_URL=https://relay.<domaine>   # seulement pour un autre relais que https://relay.relay-agent.app
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

Une étape de bloc est `effort:` ou `recup:` suivi d'une durée en secondes ou d'une distance (`400m`), avec une cible optionnelle : `@allure` en min/km (`4:25-4:40`) ou en s/km (`265-280`), `@25-30kmh`, ou une plage de fréquence cardiaque `@fc130-150`. L'allure et la vitesse ne marchent qu'en course et à vélo ; la fréquence cardiaque marche pour tous les sports. `--sport` vaut `course` (par défaut), `velo`, `marche`, `rando` ou `natation` ; `--lieu interieur` pour le tapis, le home trainer ou la piscine. Même `id` = la séance est remplacée.

Codes de sortie : 0 succès, 2 usage ou validation, 3 relais injoignable, 4 abonnement requis.

## Pont pour un agent en bac à sable

Le client tourne sur l'hôte avec la phrase ; le conteneur n'a ni phrase ni réseau sortant à ouvrir :

```sh
relay-agent pont --ecoute 172.17.0.1:8771 --dest /home/agent/workspace
```

Depuis le conteneur : `POST /sync`, `POST /rafraichir`, `POST /seance` avec `{"args": ["ajouter", "--id", …]}`, `GET /etat`. Le pont refuse d'écouter sur `0.0.0.0`.

## Messages sur l'iPhone et la montre

`relay-agent message "Bien joué ce matin" --titre Hermes` affiche une notification sur l'iPhone, reprise sur la montre quand l'iPhone est verrouillé. L'agent la chiffre avec la clé du compte ; le relais la transmet à Apple sans pouvoir la lire ni la garder, et l'app la déchiffre à l'arrivée. 2 000 octets au plus, 30 par heure, réservé aux abonnés. Depuis un conteneur : `POST /message` avec `{"texte": "…", "titre": "…"}` sur le pont ; en MCP, l'outil `message`.

## Événements : réveil et séance terminée

Avec `--sur-evenement`, `sync` et `pont` lancent une commande de ton choix chaque fois qu'une synchro apporte une nouvelle nuit de sommeil (tu viens de te réveiller) ou une séance terminée, ou quand tu réponds à l'un de ses messages depuis la notification (`D/coach/reponses/`). Chaque événement part une seule fois, et seulement s'il a moins de 6 heures :

```sh
relay-agent pont --dest /home/agent/workspace --sur-evenement /usr/local/bin/sur-evenement-relay
```

La commande reçoit l'événement en JSON dans `RELAY_EVENEMENT` :

```json
{"type": "reveil", "nuit": "2026-10-25", "fin": "2026-10-25 07:12:00 +0100", "sommeil_h": 7.5}
{"type": "seance", "id": "FC2167F2-…", "nom": "Course", "fin": "2026-10-25 19:14:00 +0100", "prevu_id": "2026-10-25-facile-40min"}
{"type": "reponse", "texte": "OK", "a": "Ce soir : 6 × 3 min", "quand": "2026-10-25T07:35:00+01:00"}
```

Le relais ne voit jamais ces événements : ils sont calculés chez toi, après déchiffrement. La détection suit la synchro : avec le pont, appelle `POST /sync` régulièrement (toutes les 5 minutes par exemple).

## Serveur MCP

Claude Desktop (`claude_desktop_config.json`) ou Cursor (`.cursor/mcp.json`) :

```json
{"mcpServers": {"relay": {"command": "relay-agent", "args": ["mcp", "--dest", "/Users/moi/relay"]}}}
```

La phrase vient de `~/.config/relay/phrase` (mode 600) : ne la mets pas dans ce fichier de configuration, souvent lisible par d'autres. `RELAY_PHRASE` reste pour les conteneurs.

Outils : `etat`, `resume`, `metriques(nom, jours)`, `seances(jours)`, `planifier(id, nom, date, blocs, echauffement_s, retour_calme_s, sport, lieu)`, `retirer(id)`, `rafraichir`, `message(texte, titre)`.

## Développement

`uv sync`, `uv run pytest -q`. Le contrat de chiffrement est dans `vecteurs/chiffrement.json`, copie de celui publié par `relay-serveur`.
