import json
from datetime import datetime

import pytest

from relay_agent import client, seance
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))
MAINTENANT = datetime.fromisoformat("2026-10-18T12:00:00+02:00")


@pytest.fixture
def monde(tmp_path):
    f = FauxRelais()
    yield tmp_path, client.Relais(f.url, IDENTITE), f
    f.arreter()


def ajouter(dest, relais, **kw):
    args = dict(id="2026-10-21-frac-6x3", nom="Frac 6 × 3 min", date="2026-10-21T18:30:00+02:00", blocs=["6x effort:180@265-280 recup:120"])
    args.update(kw)
    return seance.ajouter(dest, relais, maintenant=MAINTENANT, **args)


def local(dest):
    return json.loads((dest / "coach" / "prevu.json").read_text())["seances"]


def distant(relais_http, r):
    return json.loads(r.lire("prevu.json"))["seances"]


def test_ajoute_une_seance_complete(monde):
    dest, r, f = monde
    liste = ajouter(dest, r, echauffement=600, retour_calme=600)
    s = liste[0]
    assert s["id"] == "2026-10-21-frac-6x3" and s["echauffement"] == {"duree_s": 600} and s["retour_calme"] == {"duree_s": 600}
    assert s["blocs"] == [{"repetitions": 6, "etapes": [{"type": "effort", "duree_s": 180, "allure": {"min_s_km": 265, "max_s_km": 280}}, {"type": "recup", "duree_s": 120}]}]
    assert local(dest) == liste and distant(f, r) == liste


def test_etape_en_distance_et_allure_min_km(monde):
    dest, r, f = monde
    s = ajouter(dest, r, id="2026-10-22-400", nom="8 × 400 m", date="2026-10-22T18:30:00+02:00", blocs=["8x effort:400m@4:10-4:20 recup:90"])[0]
    assert s["blocs"][0]["etapes"][0] == {"type": "effort", "distance_m": 400, "allure": {"min_s_km": 250, "max_s_km": 260}}


def test_meme_id_remplace(monde):
    dest, r, f = monde
    ajouter(dest, r, nom="A")
    liste = ajouter(dest, r, nom="A bis")
    assert [s["nom"] for s in liste] == ["A bis"]


def test_date_passee_refusee(monde):
    dest, r, f = monde
    with pytest.raises(seance.Validation, match="passée"):
        ajouter(dest, r, date="2026-10-01T18:30:00+02:00")
    assert not (dest / "coach" / "prevu.json").exists()


def test_id_mal_forme_refuse(monde):
    dest, r, f = monde
    with pytest.raises(seance.Validation, match="AAAA-MM-JJ-"):
        ajouter(dest, r, id="frac")


def test_bloc_illisible_refuse(monde):
    dest, r, f = monde
    with pytest.raises(seance.Validation, match="bloc"):
        ajouter(dest, r, blocs=["6x effort:trois"])


def test_date_sans_fuseau_refusee(monde):
    dest, r, f = monde
    with pytest.raises(seance.Validation, match="décalage"):
        ajouter(dest, r, date="2026-10-21T18:30:00")


def test_retirer_et_inconnu(monde):
    dest, r, f = monde
    ajouter(dest, r)
    ajouter(dest, r, id="2026-10-23-b", nom="B", date="2026-10-23T18:30:00+02:00")
    assert [s["id"] for s in seance.retirer(dest, r, "2026-10-21-frac-6x3")] == ["2026-10-23-b"]
    assert [s["id"] for s in distant(f, r)] == ["2026-10-23-b"]
    with pytest.raises(seance.Validation, match="inconnu"):
        seance.retirer(dest, r, "2026-10-30-x")


def test_lister_trie_par_date(monde):
    dest, r, f = monde
    ajouter(dest, r, id="2026-10-23-b", nom="B", date="2026-10-23T18:30:00+02:00")
    ajouter(dest, r)
    assert [s["id"] for s in seance.lister(dest)] == ["2026-10-21-frac-6x3", "2026-10-23-b"]
    assert seance.formater(seance.lister(dest)).splitlines()[0].startswith("2026-10-21-frac-6x3 2026-10-21T18:30:00+02:00 Frac")
    assert seance.formater([]) == "aucune séance prévue"


def test_purger_les_passees(monde):
    dest, r, f = monde
    ajouter(dest, r)
    d = json.loads((dest / "coach" / "prevu.json").read_text())
    d["seances"].append({"id": "2026-10-10-vieille", "nom": "V", "date": "2026-10-10T18:30:00+02:00", "blocs": []})
    (dest / "coach" / "prevu.json").write_text(json.dumps(d))
    assert [s["id"] for s in seance.purger(dest, r, maintenant=MAINTENANT)] == ["2026-10-21-frac-6x3"]
    assert [s["id"] for s in distant(f, r)] == ["2026-10-21-frac-6x3"]


def test_402_restaure_le_fichier_et_remonte(monde):
    dest, r, f = monde
    ajouter(dest, r)
    avant = (dest / "coach" / "prevu.json").read_text()
    f.abonne = False
    with pytest.raises(client.AbonnementRequis):
        ajouter(dest, r, id="2026-10-23-b", nom="B", date="2026-10-23T18:30:00+02:00")
    assert (dest / "coach" / "prevu.json").read_text() == avant


def test_injoignable_restaure(tmp_path):
    r = client.Relais("http://127.0.0.1:1", IDENTITE)
    with pytest.raises(client.Injoignable):
        ajouter(tmp_path, r)
    assert not (tmp_path / "coach" / "prevu.json").exists()


def test_date_ecrite_a_la_seconde(monde):
    """Le décodeur ISO 8601 de l'app refuse les fractions de seconde : tout prevu.json deviendrait illisible."""
    dest, r, f = monde
    ajouter(dest, r, date="2026-10-21T18:30:00.5+02:00")
    assert local(dest)[0]["date"] == "2026-10-21T18:30:00+02:00"


def test_course_par_defaut_garde_l_ancien_format(monde):
    dest, r, f = monde
    s = ajouter(dest, r)[0]
    assert "sport" not in s and "lieu" not in s


def test_velo_interieur_en_kmh(monde):
    dest, r, f = monde
    s = ajouter(dest, r, id="2026-10-22-velo", nom="Home trainer", sport="velo", lieu="interieur", blocs=["3x effort:600@30-25kmh recup:300"])[0]
    assert s["sport"] == "velo" and s["lieu"] == "interieur"
    assert s["blocs"][0]["etapes"][0]["allure"] == {"min_s_km": 120, "max_s_km": 144}


def test_rando_en_frequence_cardiaque(monde):
    dest, r, f = monde
    s = ajouter(dest, r, id="2026-10-22-rando", nom="Rando", sport="rando", blocs=["1x effort:7200@fc140-120"])[0]
    assert s["blocs"][0]["etapes"][0] == {"type": "effort", "duree_s": 7200, "fc": {"min": 120, "max": 140}}


def test_allure_refusee_hors_course_et_velo(monde):
    dest, r, f = monde
    with pytest.raises(seance.Validation, match="fréquence cardiaque"):
        ajouter(dest, r, sport="natation", blocs=["4x effort:100m@2:00-2:10 recup:30"])


def test_sport_et_lieu_inconnus_refuses(monde):
    dest, r, f = monde
    with pytest.raises(seance.Validation, match="sport inconnu"):
        ajouter(dest, r, sport="ski")
    with pytest.raises(seance.Validation, match="lieu inconnu"):
        ajouter(dest, r, lieu="dehors")
