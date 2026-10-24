from relay_agent import fusion


def point(date, qty, source=""):
    return {"date": date, "qty": qty, "source": source}


def mois(points):
    return {"name": "step_count", "units": "count", "data": points}


def test_fusion_remplace_le_jour_et_trie():
    existant = mois([point("2026-10-01 00:00:00 +0200", 100), point("2026-10-03 00:00:00 +0200", 300)])
    recu = mois([point("2026-10-02 00:00:00 +0200", 200), point("2026-10-03 00:00:00 +0200", 350)])
    f = fusion.fusionner_metrique(existant, recu)
    assert [(p["date"][:10], p["qty"]) for p in f["data"]] == [("2026-10-01", 100), ("2026-10-02", 200), ("2026-10-03", 350)]
    assert (f["name"], f["units"]) == ("step_count", "count")


def test_fusion_idempotente():
    recu = mois([point("2026-10-02 00:00:00 +0200", 200)])
    une = fusion.fusionner_metrique(None, recu)
    assert fusion.fusionner_metrique(une, recu) == une


def test_fusion_mois_dans_le_desordre():
    nov = mois([point("2026-11-01 00:00:00 +0100", 5)])
    oct_ = mois([point("2026-10-31 00:00:00 +0100", 4)])
    f = fusion.fusionner_metrique(fusion.fusionner_metrique(None, nov), oct_)
    assert [p["qty"] for p in f["data"]] == [4, 5]


def test_fusion_garde_les_sources_separees():
    recu = mois([point("2026-10-02 00:00:00 +0200", 7.3, "Montre"), point("2026-10-02 00:00:00 +0200", 7.9, "AutoSleep")])
    assert len(fusion.fusionner_metrique(None, recu)["data"]) == 2


PREVUES = [{"id": "2026-10-21-matin", "nom": "Footing", "date": "2026-10-21T07:00:00+02:00"},
           {"id": "2026-10-21-soir", "nom": "Frac 6 × 3 min", "date": "2026-10-21T18:30:00+02:00"}]


def test_appariement_plus_proche():
    s = {"name": "Course", "start": "2026-10-21 18:34:02 +0200"}
    fusion.apparier(s, PREVUES)
    assert (s["prevu_id"], s["prevu_nom"]) == ("2026-10-21-soir", "Frac 6 × 3 min")


def test_appariement_ignore_marche_et_autre_jour():
    m = {"name": "Marche", "start": "2026-10-21 18:34:02 +0200"}
    fusion.apparier(m, PREVUES)
    c = {"name": "Course", "start": "2026-10-22 07:00:00 +0200"}
    fusion.apparier(c, PREVUES)
    assert "prevu_id" not in m and "prevu_id" not in c


def test_appariement_tolere_prevues_mal_formees():
    s = {"name": "Course", "start": "2026-10-21 18:34:02 +0200"}
    fusion.apparier(s, ["2026-10-21", None, {"date": 3}])
    assert "prevu_id" not in s


def test_nom_fichier_seance():
    assert fusion.nom_fichier_seance("seances/2026-10-18-ABC.json") == "2026-10-18-ABC.json"


def test_appariement_par_sport():
    prevues = PREVUES + [{"id": "2026-10-21-velo", "nom": "Vélo cool", "date": "2026-10-21T18:00:00+02:00", "sport": "velo"}]
    v = {"name": "Vélo", "start": "2026-10-21 18:34:02 +0200"}
    fusion.apparier(v, prevues)
    c = {"name": "Course", "start": "2026-10-21 18:34:02 +0200"}
    fusion.apparier(c, prevues)
    assert v["prevu_id"] == "2026-10-21-velo" and c["prevu_id"] == "2026-10-21-soir"
