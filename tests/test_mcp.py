import asyncio
import json

import pytest

from relay_agent import client, mcp_serveur
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))


@pytest.fixture
def serveur(tmp_path):
    f = FauxRelais()
    r = client.Relais(f.url, IDENTITE)
    r.deposer("etat.json", b'{"synced_at": "2026-10-18 20:00:00 +0200", "latest": {}}')
    r.deposer("metriques/step_count/2026-10.json", json.dumps({"name": "step_count", "units": "count", "data": [{"date": "2026-10-18 00:00:00 +0200", "qty": 14040, "source": ""}]}).encode())
    s = mcp_serveur.creer(r, tmp_path)
    yield s, f, tmp_path
    f.arreter()


def appeler(s, outil, **args):
    resultat = asyncio.run(s.call_tool(outil, args))
    texte = "".join(getattr(c, "text", "") for c in (resultat if isinstance(resultat, list) else getattr(resultat, "content", resultat)))
    return texte


def test_outils_listes(serveur):
    s, f, dest = serveur
    noms = {t.name for t in asyncio.run(s.list_tools())}
    assert noms == {"etat", "resume", "metriques", "seances", "planifier", "retirer", "rafraichir"}


def test_etat_apres_sync(serveur):
    s, f, dest = serveur
    texte = appeler(s, "etat")
    assert "2026-10-18 20:00:00" in texte
    assert (dest / "sante" / "etat.json").exists()


def test_metriques_renvoie_les_points(serveur):
    s, f, dest = serveur
    texte = appeler(s, "metriques", nom="step_count", jours=30)
    assert "14040" in texte


def test_planifier_passe_par_seance(serveur):
    s, f, dest = serveur
    texte = appeler(s, "planifier", id="2099-01-01-a", nom="A", date="2099-01-01T10:00:00+01:00", blocs=["1x effort:600"])
    assert "2099-01-01-a" in texte and "prevu.json" in f.blobs
    assert "aucune séance" in appeler(s, "retirer", id="2099-01-01-a")


def test_erreur_lisible_sans_trace(serveur):
    s, f, dest = serveur
    texte = appeler(s, "planifier", id="x", nom="A", date="2099-01-01T10:00:00+01:00", blocs=["1x effort:600"])
    assert "AAAA-MM-JJ" in texte and "Traceback" not in texte
    f.abonne = False
    texte = appeler(s, "planifier", id="2099-01-01-b", nom="B", date="2099-01-01T10:00:00+01:00", blocs=["1x effort:600"])
    assert "abonnement" in texte.lower()


def test_resume_sans_rafraichir(serveur):
    s, f, dest = serveur
    assert appeler(s, "resume", sans_rafraichir=True).startswith("# Résumé santé")
