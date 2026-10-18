# relay-agent : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un paquet Python `relay-agent` qui déchiffre les blobs du relais avec la phrase d'appairage, écrit les fichiers que le coaching de Julien lit déjà (`sante/metriques`, `sante/seances`, `sante/etat.json`, `coach/prevu.json`), planifie les séances, demande un rafraîchissement, calcule le résumé santé, sert un pont sans secret à un agent en bac à sable, et expose le tout en MCP.

**Architecture:** Un module par responsabilité, tous purs sauf `client.py` (HTTP) ; une commande `relay-agent` en `argparse` ; le pont et le serveur MCP sont deux façades minces sur les mêmes fonctions. L'archive locale (`dest/`) est la source de vérité du résumé ; le relais n'est qu'un tampon.

**Tech Stack:** Python 3.11+ (le paquet doit s'installer sur des machines d'agents variées), `cryptography`, `httpx`, `mcp` (SDK Python officiel, serveur stdio), `pytest` via `uv`, publication PyPI par `uv build` + `uv publish`.

**Spec:** `/Users/julienrenaudperso/Documents/git/perso/relay/docs/superpowers/specs/2026-10-18-relay-v2-design.md` (sections 1, 2, 4 et 7). Références v1 à porter : `/Users/julienrenaudperso/Documents/git/perso/OVH-perso/ansible/files/{resume-sante.py,test_resume_sante.py,seance.py,test_seance.py,hermes-sante.py (fonctions apparier/seances_prevues)}`. API du relais : `/Users/julienrenaudperso/Documents/git/perso/relay-serveur/relay_serveur/*.py`, vecteurs : `vecteurs/chiffrement.json` (copie identique à celle de relay-serveur).

## Global Constraints

- Français partout. YAGNI. Aucune donnée de santé ni phrase dans un journal ou un message d'erreur.
- Phrase d'appairage : `relay1:<id>:<jeton>:<cle>` où `cle` est 32 octets en base64url sans remplissage ; lue dans `RELAY_PHRASE`, sinon `~/.config/relay/phrase` ; refus si le fichier est lisible par le groupe ou les autres (`mode & 0o077`). URL du relais dans `RELAY_URL`.
- Chiffrement : `nonce(12) || AES-256-GCM(cle, nonce, clair, aad = id || nom)` ; les vecteurs du dépôt sont rejoués par les tests.
- Format des fichiers écrits dans `dest/` : identique à la v1 (Health Auto Export), `dest/sante/metriques/<nom>.json` fusionne tous les mois reçus, un point par (jour, source), trié par date ; `dest/sante/seances/<AAAA-MM-JJ>-<id>.json` ; `dest/sante/etat.json` ; `dest/coach/prevu.json`. Le client ne supprime jamais un fichier local.
- Appariement prévu/réalisé au `sync` : une séance `name == "Course"` du jour d'une séance prévue reçoit `prevu_id` et `prevu_nom` (la plus proche en heure).
- Le pont n'écoute que sur une adresse locale ou de pont Docker (`127.*`, `172.16-31.*`, `10.*`, `192.168.*`) et refuse `0.0.0.0`/`::` ; ses routes ne reçoivent ni ne renvoient jamais la phrase.
- Codes de sortie : 0 succès, 2 usage ou validation, 3 relais injoignable, 4 abonnement requis (`402`).

## Review Focus

- Blob dont le déchiffrement échoue (clé changée après régénération de la phrase) : `sync` signale le blob et continue les autres, code de sortie 0 avec avertissement (test en tâche 4).
- Mois reçu dans le désordre ou reçu deux fois : la fusion reste idempotente et triée (test en tâche 4).
- `seance ajouter` quand le relais répond `402` : le fichier local n'est pas modifié et la commande sort en 4 (test en tâche 5).
- Pont lancé sur `0.0.0.0` : refus immédiat (test en tâche 7).
- `resume` sans aucune donnée locale : sortie lisible, pas d'exception (test en tâche 6, hérité de la v1).

---

### Task 1: Squelette, phrase d'appairage et chiffrement

**Files:**
- Create: `pyproject.toml` (paquet `relay_agent`, script `relay-agent = "relay_agent.cli:main"`, dépendances `cryptography`, `httpx`, `mcp`), `relay_agent/__init__.py`, `relay_agent/phrase.py`, `relay_agent/chiffrement.py`, `tests/test_phrase.py`, `tests/test_chiffrement.py`, `README.md` (rôle, installation `pip install relay-agent`, appairage), `.gitignore`

**Interfaces:**
- Produces: `phrase.Identite(id: str, jeton: str, cle: bytes)`, `phrase.analyser(texte) -> Identite` (`ValueError` si préfixe ou longueurs faux), `phrase.charger(env=os.environ, chemin=~/.config/relay/phrase) -> Identite` (`PermissionError` si le fichier est trop ouvert), `phrase.url(env) -> str` (défaut `https://relay.example.invalid` tant que le domaine n'est pas connu, à remplacer avant publication), `chiffrement.chiffrer(cle, id, nom, clair) -> bytes`, `chiffrement.dechiffrer(cle, id, nom, blob) -> bytes` (`ValueError` si le tag ne passe pas).

- [ ] **Step 1: Tests** : `test_phrase_valide`, `test_phrase_prefixe_faux`, `test_phrase_cle_trop_courte`, `test_charger_depuis_env`, `test_charger_fichier_trop_ouvert_refuse` (mode 0644 → `PermissionError`), `test_vecteurs_rejoues` (chaque vecteur : `chiffrer` avec le nonce du vecteur injecté via un paramètre `nonce=` → `blob_chiffre`, `dechiffrer` → `clair`), `test_blob_altere_refuse`, `test_aad_lie_le_nom`.
- [ ] **Step 2: Vérifier l'échec** — `uv run pytest -q`. **Step 3: Implémenter.** **Step 4: Vérifier le succès.** **Step 5: Commit** — `git commit -am "Phrase d'appairage et chiffrement AES-256-GCM conformes aux vecteurs"`

### Task 2: Client HTTP du relais

**Files:**
- Create: `relay_agent/client.py`, `tests/test_client.py` (serveur `http.server` éphémère qui rejoue les réponses du relais)

**Interfaces:**
- Produces: `client.Relais(url, identite)` avec `lister(depuis=None) -> list[dict]`, `lire(nom) -> bytes` (déchiffré), `deposer(nom, clair) -> float` (chiffre puis `PUT`), `retirer(nom) -> bool`, `rafraichir() -> tuple[int, dict]`. Erreurs : `client.Injoignable` (réseau), `client.AbonnementRequis` (`402`), `client.Refus(code, status)` (autres 4xx/5xx). En-tête `Authorization: Bearer <jeton>`, délai 30 s (60 s pour `rafraichir`).

- [ ] **Step 1: Tests** : `test_deposer_chiffre_et_lire_dechiffre` (le faux serveur garde les octets ; le test vérifie qu'ils ne contiennent pas le clair), `test_402_leve_abonnement_requis`, `test_injoignable`, `test_rafraichir_renvoie_code_et_corps`.
- [ ] **Step 2-5** : échec, implémentation, succès, commit — `git commit -am "Client HTTP du relais"`

### Task 3: Fusion des métriques et appariement

**Files:**
- Create: `relay_agent/fusion.py`, `tests/test_fusion.py`

**Interfaces:**
- Produces: `fusion.fusionner_metrique(existant: dict | None, mois: dict) -> dict` (format HAE : `name`, `units`, `data` ; clé `(date[:10], source)`, le reçu remplace l'existant, tri par date), `fusion.apparier(seance: dict, prevues: list[dict]) -> None` (porté de `hermes-sante.py`, plus proche en heure), `fusion.nom_fichier_seance(blob_nom) -> str`.

- [ ] **Step 1: Tests** : `test_fusion_remplace_le_jour_et_trie`, `test_fusion_idempotente`, `test_fusion_mois_dans_le_desordre`, `test_appariement_plus_proche` (repris de `test_hermes_sante.py`), `test_appariement_ignore_marche`.
- [ ] **Step 2-5** : échec, implémentation, succès, commit — `git commit -am "Fusion des mois en fichiers Health Auto Export, appariement prévu/réalisé"`

### Task 4: `sync`

**Files:**
- Create: `relay_agent/sync.py`, `tests/test_sync.py` (faux relais de la tâche 2)

**Interfaces:**
- Produces: `sync.synchroniser(relais, dest: Path, journal=print) -> Rapport` avec `Rapport(blobs_lus, blobs_ignores: list[str], erreurs: list[str])`. État dans `dest/.relay/sync.json` (`maj` par blob déjà intégré) ; ne redemande que les blobs dont `maj` a changé ; `metriques/<nom>/<mois>.json` → fusion dans `dest/sante/metriques/<nom>.json` ; `seances/*` → fichier + appariement avec `dest/coach/prevu.json` ; `etat.json` → `dest/sante/etat.json` ; `prevu.json` → `dest/coach/prevu.json`. Écriture atomique (`.tmp` puis `replace`).

- [ ] **Step 1: Tests** : `test_premiere_synchro_ecrit_tout`, `test_seconde_synchro_ne_relit_que_les_modifies`, `test_blob_indechiffrable_signale_et_continue`, `test_seance_appariee_avec_prevu_local`, `test_ne_supprime_jamais_un_fichier_local` (un blob retiré du relais laisse le fichier).
- [ ] **Step 2-5** : échec, implémentation, succès, commit — `git commit -am "sync : tire, déchiffre, fusionne, apparie"`

### Task 5: `seance` et `rafraichir`

**Files:**
- Create: `relay_agent/seance.py` (porté de `seance.py` v1 : mêmes sous-commandes, mêmes messages, même format), `relay_agent/rafraichir.py`, `tests/test_seance.py` (tests v1 portés + nouveaux), `tests/test_rafraichir.py`

**Interfaces:**
- Produces: `seance.ajouter/retirer/lister/purger(prevu_local: Path, relais) -> list[dict]` : modifie `dest/coach/prevu.json` puis `relais.deposer("prevu.json", ...)` ; en cas d'`AbonnementRequis` ou d'`Injoignable`, le fichier local est restauré et l'erreur remonte. `rafraichir.demander(relais) -> dict` (`{"http", "corps", "erreur"}`, comme le client v1).

- [ ] **Step 1: Tests** : les dix tests de `test_seance.py` v1 adaptés à l'API en fonctions, plus `test_402_restaure_le_fichier_et_remonte`, `test_injoignable_restaure`, `test_rafraichir_dict_v1`.
- [ ] **Step 2-5** : échec, implémentation, succès, commit — `git commit -am "seance et rafraichir, à la sémantique de la v1"`

### Task 6: `resume`

**Files:**
- Create: `relay_agent/resume.py` (porté de `resume-sante.py` : le script devient `resume(workspace: Path, maintenant: datetime, aujourd_hui: date, reponse_rafraichissement: dict | None) -> str`), `tests/test_resume.py` (les 21 tests v1 portés : `run`/`run_coach` appellent la fonction au lieu d'un sous-processus)

**Interfaces:**
- Consumes: `rafraichir.demander`.
- Produces: `resume.resume(...) -> str`, texte identique à la v1 ligne pour ligne (les tests le garantissent).

- [ ] **Step 1: Porter les tests**, **Step 2: Vérifier l'échec**, **Step 3: Porter le script** en fonction sans variable globale, **Step 4: Vérifier le succès**, **Step 5: Commit** — `git commit -am "resume : le résumé santé v1, en fonction"`

### Task 7: Ligne de commande et pont

**Files:**
- Create: `relay_agent/cli.py`, `relay_agent/pont.py`, `tests/test_cli.py`, `tests/test_pont.py`

**Interfaces:**
- Produces: `relay-agent sync --dest D`, `relay-agent rafraichir`, `relay-agent seance ajouter|retirer|lister|purger … --dest D`, `relay-agent resume --dest D [--sans-rafraichir]`, `relay-agent pont --ecoute 172.17.0.1:8771 --dest D`, `relay-agent mcp --dest D` ; codes de sortie des contraintes globales. Pont : `ThreadingHTTPServer`, routes `POST /sync`, `POST /rafraichir`, `POST /seance` (`{"args": [...]}` → sortie texte et code), `GET /etat` (contenu de `dest/sante/etat.json`), `404` ailleurs ; refuse les adresses non locales.

- [ ] **Step 1: Tests** : `test_cli_sans_phrase_sort_en_2`, `test_cli_seance_402_sort_en_4`, `test_pont_refuse_0000`, `test_pont_sync_et_etat` (faux relais), `test_pont_seance_renvoie_sortie_et_code`, `test_pont_ne_renvoie_jamais_la_phrase` (la réponse de chaque route ne contient ni jeton ni clé).
- [ ] **Step 2-5** : échec, implémentation, succès, commit — `git commit -am "Ligne de commande et pont sans secret pour un agent en bac à sable"`

### Task 8: Serveur MCP

**Files:**
- Create: `relay_agent/mcp_serveur.py`, `tests/test_mcp.py`

**Interfaces:**
- Produces: serveur MCP stdio (`mcp.server.fastmcp.FastMCP`) nommé `relay`, outils : `etat()`, `resume(sans_rafraichir: bool = False)`, `metriques(nom: str, jours: int = 7)`, `seances(jours: int = 7)`, `planifier(id, nom, date, blocs: list[str], echauffement_s=0, retour_calme_s=0)`, `retirer(id)`, `rafraichir()`. Chaque outil fait un `sync` avant de lire. Les erreurs reviennent en texte lisible, jamais en trace.

- [ ] **Step 1: Tests** (client MCP en mémoire du SDK) : `test_outils_listes`, `test_etat_apres_sync`, `test_planifier_passe_par_seance`, `test_erreur_lisible_sans_trace`.
- [ ] **Step 2-5** : échec, implémentation, succès, commit — `git commit -am "Serveur MCP"`

### Task 9: Publication et README

- [ ] **Step 1:** README complet : installation, phrase, variables, les six commandes, exemple de configuration MCP pour Claude Desktop et Cursor, exemple de pont pour un agent en bac à sable.
- [ ] **Step 2:** `uv build` puis `uv publish --dry-run` ; publication réelle sur PyPI quand le domaine par défaut est connu (Julien crée le compte PyPI et fournit un jeton).
- [ ] **Step 3:** Commit — `git commit -am "README et publication"`
