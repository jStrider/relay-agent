# relay-agent

English · [Français](https://github.com/jStrider/relay-agent/blob/main/README.fr.md)

Client of [Relay](https://github.com/jStrider/relay) for an AI agent. The Relay app uploads its user's Apple Health data to a relay, encrypted with a key that never leaves the iPhone. This client decrypts the data with the pairing phrase, writes it to files the agent can read, schedules running workouts that go to the Watch, and asks the iPhone for a refresh. It runs as a command-line tool, as a secret-free bridge for a sandboxed agent, and as an MCP server.

## Installation and pairing

```sh
uv tool install git+https://github.com/jStrider/relay-agent   # or: pipx install git+https://github.com/jStrider/relay-agent
mkdir -p ~/.config/relay && (umask 077; printf '%s' 'relay1:…' > ~/.config/relay/phrase)
export RELAY_URL=https://relay.<domain>   # only for a relay other than https://relay.relay-agent.app
```

The phrase `relay1:<id>:<jeton>:<cle>` is shown in the app, Settings tab, as text and as a QR code. It gives access to all the data, so the client refuses a file that other users can read. `RELAY_PHRASE` overrides the file.

## Link an agent with a short code (recommended)

```sh
relay-agent relier
# Dans l'app Relay, « Relier un agent », saisis : K7Q2-M6XA
# Code à comparer avec celui de l'app : 327365
# Appairé : phrase enregistrée dans ~/.config/relay/phrase
```

The command prints its messages in French. Above, it asks you to enter `K7Q2-M6XA` under "Link an agent" in the Relay app, then shows a code to compare with the one in the app.

The agent and the app exchange ephemeral keys through the relay and show the same six-digit code. The agent first publishes only a SHA-256 commitment to its key and reveals the key once the app has posted its own; the app checks the key against the commitment. A malicious relay therefore cannot pick keys that make the two codes match. The phrase is sent encrypted once you confirm in the app. The relay only sees ciphertext. `--oui` replaces a phrase that is already saved. From the bridge: `POST /relier` returns the session, and `GET /relier/<session>` gives the state (`attente_app`, `code`, `appairé`, `expiré`) and the code.

## Command line

| Command | Effect | Output |
|---|---|---|
| `relay-agent sync --dest D` | Pulls and decrypts changed blobs, writes `D/sante/metriques/<nom>.json`, `D/sante/seances/*.json`, `D/sante/etat.json`, `D/coach/prevu.json` | summary on stderr |
| `relay-agent resume --dest D [--sans-rafraichir]` | Asks the iPhone for a fresh sync, syncs, prints the dated health summary | text |
| `relay-agent rafraichir` | Wakes the iPhone and waits for its sync | `{"http": 200, "corps": {…}, "erreur": null}` |
| `relay-agent seance ajouter --id 2026-10-21-frac-6x3 --nom "Frac 6 × 3 min" --date 2026-10-21T18:30:00+02:00 --echauffement 600 --bloc "6x effort:180@4:25-4:40 recup:120" --retour-calme 600 --dest D` | Schedules a workout (locally, then on the relay) | list of workouts |
| `relay-agent seance retirer <id>` · `lister` · `purger` | Removes one, lists them, removes past workouts | list of workouts |
| `relay-agent pont --ecoute 172.17.0.1:8771 --dest D` | Secret-free HTTP bridge for a container | log on stderr |
| `relay-agent mcp --dest D` | MCP server on stdio | |
| `relay-agent relier [--oui]` | Pairing with a short code (see above) | session, code, confirmation |

A block step is `effort:` or `recup:` (recovery) followed by a duration in seconds or a distance (`400m`), with an optional target: `@pace` in min/km (`4:25-4:40`) or s/km (`265-280`), `@25-30kmh`, or a heart rate range `@fc130-150`. Pace and speed work for running and cycling only; heart rate works for every sport. `--sport` is `course` (running, default), `velo` (cycling), `marche` (walking), `rando` (hiking) or `natation` (swimming); `--lieu interieur` means treadmill, indoor trainer or pool. Same `id` means the workout is replaced.

Exit codes: 0 success, 2 usage or validation error, 3 relay unreachable, 4 subscription required.

## Bridge for a sandboxed agent

The client runs on the host with the phrase. The container has no phrase and needs no outbound network access:

```sh
relay-agent pont --ecoute 172.17.0.1:8771 --dest /home/agent/workspace
```

From the container: `POST /sync`, `POST /rafraichir`, `POST /seance` with `{"args": ["ajouter", "--id", …]}`, `GET /etat`. The bridge refuses to listen on `0.0.0.0`.

## Messages to the iPhone and the watch

`relay-agent message "Well done this morning" --titre Hermes` shows a notification on the iPhone, mirrored on the watch when the iPhone is locked. The agent encrypts it with the account key; the relay forwards it to Apple without being able to read it or keeping it, and the app decrypts it on arrival. 2,000 bytes at most, 30 per hour, subscribers only. From a container: `POST /message` with `{"texte": "…", "titre": "…"}` on the bridge; with MCP, the `message` tool.

## Events: wake-up and finished workout

With `--sur-evenement`, `sync` and `pont` run a command of yours each time a sync brings a new night of sleep (you just woke up) or a finished workout, or when you reply to one of its messages from the notification (`D/coach/reponses/`). Each event fires once, and only if it is less than 6 hours old:

```sh
relay-agent pont --dest /home/agent/workspace --sur-evenement /usr/local/bin/on-relay-event
```

The command receives the event as JSON in `RELAY_EVENEMENT`:

```json
{"type": "reveil", "nuit": "2026-10-25", "fin": "2026-10-25 07:12:00 +0100", "sommeil_h": 7.5}
{"type": "seance", "id": "FC2167F2-…", "nom": "Course", "fin": "2026-10-25 19:14:00 +0100", "prevu_id": "2026-10-25-facile-40min"}
{"type": "reponse", "texte": "OK", "a": "Tonight: 6 × 3 min", "quand": "2026-10-25T07:35:00+01:00"}
```

The relay never sees these events: they are computed on your side, after decryption. Detection follows the sync, so with the bridge, call `POST /sync` regularly (every 5 minutes for example).

## MCP server

Claude Desktop (`claude_desktop_config.json`) or Cursor (`.cursor/mcp.json`):

```json
{"mcpServers": {"relay": {"command": "relay-agent", "args": ["mcp", "--dest", "/Users/me/relay"]}}}
```

The phrase comes from `~/.config/relay/phrase` (mode 600). Do not put it in this configuration file, which other users can often read. `RELAY_PHRASE` remains for containers.

Tools: `etat`, `resume`, `metriques(nom, jours)`, `seances(jours)`, `planifier(id, nom, date, blocs, echauffement_s, retour_calme_s, sport, lieu)`, `retirer(id)`, `rafraichir`, `message(texte, titre)`.

## Development

`uv sync`, `uv run pytest -q`. The encryption contract is in `vecteurs/chiffrement.json`, a copy of the one published by `relay-serveur`.
