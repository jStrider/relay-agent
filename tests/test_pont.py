import json
import threading
import urllib.error
import urllib.request

import pytest

from relay_agent import client, pont
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))


@pytest.fixture
def monde(tmp_path):
    f = FauxRelais()
    r = client.Relais(f.url, IDENTITE)
    r.deposer("etat.json", b'{"synced_at": "2026-10-18 20:00:00 +0200"}')
    serveur = pont.creer("127.0.0.1", 0, r, tmp_path)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{serveur.server_address[1]}"
    yield url, f, tmp_path
    serveur.shutdown()
    serveur.server_close()
    f.arreter()


def appel(url, methode, chemin, corps=None):
    req = urllib.request.Request(url + chemin, method=methode, data=json.dumps(corps).encode() if corps is not None else None,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as rep:
            return rep.status, rep.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def test_pont_refuse_0000(tmp_path):
    for adresse in ("0.0.0.0", "::", "", "8.8.8.8"):
        with pytest.raises(ValueError):
            pont.creer(adresse, 0, None, tmp_path)


def test_pont_sync_et_etat(monde):
    url, f, dest = monde
    code, corps = appel(url, "POST", "/sync")
    assert code == 200 and json.loads(corps)["blobs_lus"] == 1
    code, corps = appel(url, "GET", "/etat")
    assert code == 200 and json.loads(corps)["synced_at"].startswith("2026-10-18")


def test_pont_rafraichir(monde):
    url, f, dest = monde
    code, corps = appel(url, "POST", "/rafraichir")
    assert code == 200 and json.loads(corps)["http"] == 200


def test_pont_seance_renvoie_sortie_et_code(monde):
    url, f, dest = monde
    code, corps = appel(url, "POST", "/seance", {"args": ["ajouter", "--id", "2099-01-01-a", "--nom", "A", "--date", "2099-01-01T10:00:00+01:00", "--bloc", "1x effort:600"]})
    assert code == 200 and json.loads(corps)["code"] == 0 and "2099-01-01-a" in json.loads(corps)["sortie"]
    code, corps = appel(url, "POST", "/seance", {"args": ["ajouter", "--id", "x"]})
    assert code == 200 and json.loads(corps)["code"] == 2


def test_pont_ne_renvoie_jamais_la_phrase(monde):
    url, f, dest = monde
    reponses = [appel(url, "POST", "/sync")[1], appel(url, "GET", "/etat")[1], appel(url, "POST", "/rafraichir")[1],
                appel(url, "POST", "/seance", {"args": ["lister"]})[1], appel(url, "GET", "/autre")[1]]
    for r in reponses:
        assert IDENTITE.jeton not in r and IDENTITE.cle.hex() not in r and "relay1:" not in r


def test_pont_404_ailleurs(monde):
    url, f, dest = monde
    assert appel(url, "GET", "/autre")[0] == 404
