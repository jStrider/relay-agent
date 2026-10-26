import json

import pytest

from relay_agent import client, sync
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))


@pytest.fixture
def relais():
    f = FauxRelais()
    yield f
    f.arreter()


def deposer(relais, nom, obj, identite=IDENTITE):
    client.Relais(relais.url, identite).deposer(nom, json.dumps(obj).encode())


def mois(points):
    return {"name": "step_count", "units": "count", "data": [{"date": d, "qty": q, "source": ""} for d, q in points]}


def test_premiere_synchro_ecrit_tout(relais, tmp_path):
    deposer(relais, "metriques/step_count/2026-09.json", mois([("2026-09-30 00:00:00 +0200", 9000)]))
    deposer(relais, "metriques/step_count/2026-10.json", mois([("2026-10-01 00:00:00 +0200", 10000)]))
    deposer(relais, "seances/2026-10-21-W1.json", {"id": "W1", "name": "Course", "start": "2026-10-21 18:34:02 +0200"})
    deposer(relais, "etat.json", {"synced_at": "x"})
    deposer(relais, "prevu.json", {"seances": [{"id": "2026-10-21-frac", "nom": "Frac", "date": "2026-10-21T18:30:00+02:00"}]})
    rapport = sync.synchroniser(client.Relais(relais.url, IDENTITE), tmp_path, journal=lambda *a: None)
    assert rapport.blobs_lus == 5 and rapport.blobs_ignores == []
    pas = json.loads((tmp_path / "sante" / "metriques" / "step_count.json").read_text())
    assert [p["qty"] for p in pas["data"]] == [9000, 10000]
    seance = json.loads((tmp_path / "sante" / "seances" / "2026-10-21-W1.json").read_text())
    assert seance["prevu_id"] == "2026-10-21-frac"
    assert json.loads((tmp_path / "sante" / "etat.json").read_text()) == {"synced_at": "x"}
    assert "seances" in json.loads((tmp_path / "coach" / "prevu.json").read_text())


def test_seconde_synchro_ne_relit_que_les_modifies(relais, tmp_path):
    deposer(relais, "etat.json", {"synced_at": "1"})
    r = client.Relais(relais.url, IDENTITE)
    sync.synchroniser(r, tmp_path, journal=lambda *a: None)
    relais.requetes.clear()
    assert sync.synchroniser(r, tmp_path, journal=lambda *a: None).blobs_lus == 0
    assert not any(m == "GET" and p.startswith("/blobs/") for m, p in relais.requetes)
    deposer(relais, "etat.json", {"synced_at": "2"})
    assert sync.synchroniser(r, tmp_path, journal=lambda *a: None).blobs_lus == 1
    assert json.loads((tmp_path / "sante" / "etat.json").read_text())["synced_at"] == "2"


def test_blob_indechiffrable_signale_et_continue(relais, tmp_path):
    deposer(relais, "etat.json", {"synced_at": "1"}, identite=Identite(IDENTITE.id, IDENTITE.jeton, bytes(32)))
    deposer(relais, "metriques/step_count/2026-10.json", mois([("2026-10-01 00:00:00 +0200", 1)]))
    rapport = sync.synchroniser(client.Relais(relais.url, IDENTITE), tmp_path, journal=lambda *a: None)
    assert rapport.blobs_lus == 1 and rapport.blobs_ignores == ["etat.json"]
    assert (tmp_path / "sante" / "metriques" / "step_count.json").exists()
    assert not (tmp_path / "sante" / "etat.json").exists()


def test_ne_supprime_jamais_un_fichier_local(relais, tmp_path):
    deposer(relais, "seances/2026-10-21-W1.json", {"id": "W1", "name": "Marche", "start": "2026-10-21 18:34:02 +0200"})
    r = client.Relais(relais.url, IDENTITE)
    sync.synchroniser(r, tmp_path, journal=lambda *a: None)
    r.retirer("seances/2026-10-21-W1.json")
    sync.synchroniser(r, tmp_path, journal=lambda *a: None)
    assert (tmp_path / "sante" / "seances" / "2026-10-21-W1.json").exists()


def test_ecriture_atomique_sans_tmp_residuel(relais, tmp_path):
    deposer(relais, "etat.json", {"synced_at": "1"})
    sync.synchroniser(client.Relais(relais.url, IDENTITE), tmp_path, journal=lambda *a: None)
    assert not list((tmp_path / "sante").rglob("*.tmp"))


def test_reponse_rangee_puis_retiree_du_relais(relais, tmp_path):
    deposer(relais, "reponses/1793000000000.json", {"texte": "OK", "a": "Séance", "quand": "2026-10-25T07:35:00+01:00"})
    rapport = sync.synchroniser(client.Relais(relais.url, IDENTITE), tmp_path, journal=lambda *a: None)
    assert rapport.blobs_lus == 1
    assert json.loads((tmp_path / "coach" / "reponses" / "1793000000000.json").read_text())["texte"] == "OK"
    assert "reponses/1793000000000.json" not in relais.blobs
