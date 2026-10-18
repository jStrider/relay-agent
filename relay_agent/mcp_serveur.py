"""Serveur MCP `relay` (stdio) : les mêmes fonctions que la ligne de commande, en outils pour Claude, ChatGPT,
Cursor ou tout client MCP. Chaque outil synchronise avant de lire ; les erreurs reviennent en texte, jamais en trace."""

import json
from datetime import datetime, timedelta
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import client, rafraichir, resume, seance, sync
from .client import Relais


def creer(relais: Relais, dest: Path) -> MCPServer:
    dest = Path(dest)
    s = MCPServer("relay", instructions="Données Santé et séances de course d'un utilisateur de Relay. Un chiffre se dit avec l'heure de son dernier échantillon (outil etat).")

    def _sync():
        sync.synchroniser(relais, dest, journal=lambda m: None)

    def _texte(f):
        try:
            return f()
        except seance.Validation as e:
            return f"refusé : {e}"
        except client.AbonnementRequis as e:
            return f"abonnement requis sur le relais : {e}"
        except client.Injoignable as e:
            return f"relais injoignable : {e}"
        except client.Refus as e:
            return f"relais : {e}"
        except OSError as e:
            return f"erreur de fichier : {type(e).__name__}"

    @s.tool(description="Heure de la dernière synchro de l'app et du dernier échantillon par type (contenu de etat.json).")
    def etat() -> str:
        def f():
            _sync()
            chemin = dest / "sante" / "etat.json"
            return chemin.read_text() if chemin.exists() else "aucune synchro reçue"
        return _texte(f)

    @s.tool(name="resume", description="Résumé santé calculé : sommeil, récupération, activité, nutrition, poids, séances, avec l'heure des données.")
    def resume_(sans_rafraichir: bool = False) -> str:
        def f():
            reponse = None if sans_rafraichir else rafraichir.demander(relais)
            _sync()
            maintenant = datetime.now().astimezone()
            return resume.resume(dest, maintenant, maintenant.date(), reponse)
        return _texte(f)

    @s.tool(description="Points journaliers d'une métrique (step_count, dietary_energy, protein, weight_body_mass, sleep_analysis…) sur N jours.")
    def metriques(nom: str, jours: int = 7) -> str:
        def f():
            _sync()
            chemin = dest / "sante" / "metriques" / f"{nom}.json"
            if not chemin.exists():
                return f"aucune métrique {nom}"
            d = json.loads(chemin.read_text())
            depuis = (datetime.now() - timedelta(days=jours)).strftime("%Y-%m-%d")
            points = [p for p in d.get("data", []) if str(p.get("date", ""))[:10] >= depuis]
            return json.dumps({"name": d.get("name"), "units": d.get("units"), "data": points}, ensure_ascii=False)
        return _texte(f)

    @s.tool(description="Séances réalisées sur N jours : résumé de chaque fichier de séance (nom, début, durée, distance, FC, séance prévue appariée).")
    def seances(jours: int = 7) -> str:
        def f():
            _sync()
            depuis = (datetime.now() - timedelta(days=jours)).strftime("%Y-%m-%d")
            dossier = dest / "sante" / "seances"
            out = []
            for fichier in sorted(dossier.glob("*.json")) if dossier.exists() else []:
                if fichier.name[:10] < depuis:
                    continue
                w = json.loads(fichier.read_text())
                out.append({k: w.get(k) for k in ("id", "name", "start", "end", "duration", "distance", "avgHeartRate", "prevu_id", "prevu_nom")})
            return json.dumps(out, ensure_ascii=False) if out else "aucune séance sur la période"
        return _texte(f)

    @s.tool(description="Planifie une séance de course qui part sur la montre. blocs : liste de « 6x effort:180@4:25-4:40 recup:120 » ; une étape est effort: ou recup: suivi d'une durée en secondes ou d'une distance (400m), avec @allure optionnelle.")
    def planifier(id: str, nom: str, date: str, blocs: list[str], echauffement_s: int = 0, retour_calme_s: int = 0) -> str:
        return _texte(lambda: seance.formater(seance.ajouter(dest, relais, id, nom, date, blocs, echauffement_s, retour_calme_s)))

    @s.tool(description="Retire une séance planifiée (elle disparaît de la montre).")
    def retirer(id: str) -> str:
        return _texte(lambda: seance.formater(seance.retirer(dest, relais, id)))

    @s.tool(name="rafraichir", description="Demande à l'iPhone une synchro fraîche (jusqu'à 25 s) ; renvoie le code HTTP et l'état.")
    def rafraichir_() -> str:
        return _texte(lambda: json.dumps(rafraichir.demander(relais), ensure_ascii=False))

    return s


def servir(relais: Relais, dest: Path) -> None:
    creer(relais, dest).run("stdio")
