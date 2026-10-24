"""Ligne de commande `relay-agent` : sync, rafraichir, seance, resume, pont, mcp, relier.
Codes de sortie : 0 succès, 2 usage ou validation, 3 relais injoignable, 4 abonnement requis."""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from . import appairage, client, evenements, phrase, rafraichir, resume, seance, sync

PARIS_NOW = lambda: datetime.now().astimezone()  # noqa: E731


def _relais(env) -> client.Relais:
    return client.Relais(phrase.url(env), phrase.charger(env=env, chemin=Path(env.get("HOME", str(Path.home()))) / ".config" / "relay" / "phrase"))


class _Analyseur(argparse.ArgumentParser):
    """argparse qui renvoie ses messages au lieu de les écrire sur stderr : le pont les transmet à l'agent."""

    def error(self, message):
        raise argparse.ArgumentError(None, f"{message}\n{self.format_usage()}")

    def exit(self, status=0, message=None):
        raise argparse.ArgumentError(None, message or self.format_help())


def executer_seance(args: list[str], dest: Path, relais: client.Relais) -> tuple[int, str]:
    """Sous-commandes de séance, en (code, sortie texte) : la CLI et le pont s'en servent."""
    p = _Analyseur(prog="relay-agent seance", add_help=True, exit_on_error=False)
    sub = p.add_subparsers(dest="commande", required=True)
    a = sub.add_parser("ajouter")
    a.add_argument("--id", required=True)
    a.add_argument("--nom", required=True)
    a.add_argument("--date", required=True)
    a.add_argument("--echauffement", type=int, default=0)
    a.add_argument("--retour-calme", type=int, default=0)
    a.add_argument("--bloc", action="append", required=True)
    r = sub.add_parser("retirer")
    r.add_argument("id")
    sub.add_parser("lister")
    sub.add_parser("purger")
    try:
        n = p.parse_args(args)
    except argparse.ArgumentError as e:
        return 2, f"arguments refusés : {e.message}"
    try:
        if n.commande == "ajouter":
            liste = seance.ajouter(dest, relais, n.id, n.nom, n.date, n.bloc, n.echauffement, n.retour_calme)
        elif n.commande == "retirer":
            liste = seance.retirer(dest, relais, n.id)
        elif n.commande == "purger":
            liste = seance.purger(dest, relais)
        else:
            liste = seance.lister(dest)
        return 0, seance.formater(liste)
    except seance.Validation as e:
        return 2, str(e)
    except client.AbonnementRequis as e:
        return 4, f"abonnement requis : {e}"
    except client.Injoignable as e:
        return 3, str(e)
    except client.Refus as e:
        return 3, str(e)


def relier(env, forcer: bool, delai: float) -> int:
    """Affiche la session à saisir dans l'app, puis le code à comparer, puis enregistre la phrase reçue."""
    chemin = Path(env.get("HOME", str(Path.home()))) / ".config" / "relay" / "phrase"
    if chemin.exists() and not forcer:
        print(f"{chemin} existe déjà : relance avec --oui pour la remplacer", file=sys.stderr)
        return 2
    a = appairage.Appairage(phrase.url(env))
    try:
        session = a.ouvrir()
        print(f"Dans l'app Relay, « Relier un agent », saisis : {session[:4]}-{session[4:]}", flush=True)
        code = a.attendre_cle_app(delai=delai)
        print(f"Code à comparer avec celui de l'app : {code}", flush=True)
        texte = a.attendre_identite(delai=delai)
    except (TimeoutError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 3
    except Exception as e:  # réseau
        print(f"relais injoignable : {type(e).__name__}", file=sys.stderr)
        return 3
    appairage.enregistrer_phrase(texte, chemin, forcer=True)
    print(f"Appairé : phrase enregistrée dans {chemin}")
    return 0


def main(argv: list[str] | None = None, env=None) -> int:
    env = os.environ if env is None else env
    p = argparse.ArgumentParser(prog="relay-agent", description=__doc__)
    sub = p.add_subparsers(dest="commande", required=True)
    for nom in ("sync", "resume", "pont", "mcp", "seance"):
        s = sub.add_parser(nom)
        s.add_argument("--dest", type=Path, default=Path("/workspace"))
        if nom == "resume":
            s.add_argument("--sans-rafraichir", action="store_true")
        if nom == "pont":
            s.add_argument("--ecoute", default="172.17.0.1:8771")
        if nom in ("sync", "pont"):
            s.add_argument("--sur-evenement", metavar="COMMANDE",
                           help="commande lancée à chaque réveil ou séance terminée, l'événement en JSON dans RELAY_EVENEMENT")
        if nom == "seance":
            s.add_argument("args", nargs=argparse.REMAINDER)
    sub.add_parser("rafraichir")
    rel = sub.add_parser("relier", help="relier cet agent à l'app par un code court, sans manipuler la phrase")
    rel.add_argument("--oui", action="store_true", help="remplacer une phrase déjà enregistrée")
    rel.add_argument("--delai", type=float, default=600, help="secondes d'attente de l'app")
    n = p.parse_args(argv)
    if n.commande == "relier":
        return relier(env, n.oui, n.delai)
    try:
        relais = _relais(env)
    except (ValueError, PermissionError) as e:
        print(str(e), file=sys.stderr)
        return 2
    try:
        if n.commande == "sync":
            sync.synchroniser(relais, n.dest, journal=lambda m: print(m, file=sys.stderr))
            if n.sur_evenement:
                evenements.declencher(n.sur_evenement, evenements.detecter(n.dest, PARIS_NOW()), journal=lambda m: print(m, file=sys.stderr))
            return 0
        if n.commande == "rafraichir":
            print(json.dumps(rafraichir.demander(relais), ensure_ascii=False))
            return 0
        if n.commande == "resume":
            reponse = None if n.sans_rafraichir else rafraichir.demander(relais)
            try:
                sync.synchroniser(relais, n.dest, journal=lambda m: None)  # le résumé lit toujours l'archive à jour
            except (client.Injoignable, client.Refus) as e:  # le résumé se calcule quand même, sur l'archive locale
                print(f"synchro impossible, résumé sur l'archive locale : {e}", file=sys.stderr)
                reponse = reponse or {"http": 0, "corps": None, "erreur": str(e)}
            print(resume.resume(n.dest, PARIS_NOW(), PARIS_NOW().date(), reponse))
            return 0
        if n.commande == "seance":
            args = [a for a in n.args if a != "--"]
            if "--dest" in args:  # le reste des arguments a tout capturé, y compris --dest
                i = args.index("--dest")
                n.dest = Path(args[i + 1])
                del args[i:i + 2]
            for i, a in enumerate(args):
                if a.startswith("--dest="):
                    n.dest = Path(a.split("=", 1)[1])
                    del args[i]
                    break
            code, sortie = executer_seance(args, n.dest, relais)
            print(sortie, file=sys.stderr if code else sys.stdout)
            return code
        if n.commande == "pont":
            from . import pont
            hote, port = n.ecoute.rsplit(":", 1)
            serveur = pont.creer(hote, int(port), relais, n.dest, Path(env.get("HOME", str(Path.home()))) / ".config" / "relay" / "phrase",
                                 sur_evenement=n.sur_evenement)
            print(f"pont sur {n.ecoute}, dest {n.dest}", file=sys.stderr)
            serveur.serve_forever()
            return 0
        if n.commande == "mcp":
            from . import mcp_serveur
            mcp_serveur.servir(relais, n.dest)
            return 0
    except client.AbonnementRequis as e:
        print(f"abonnement requis : {e}", file=sys.stderr)
        return 4
    except client.Injoignable as e:
        print(str(e), file=sys.stderr)
        return 3
    except client.Refus as e:
        print(str(e), file=sys.stderr)
        return 3
    return 2


if __name__ == "__main__":
    sys.exit(main())
