import json
import sys
import time
from datetime import datetime

from relay_agent import evenements

MAINTENANT = datetime.fromisoformat("2026-10-25T07:40:00+01:00")


def nuit(dest, date, fin, core=5.0, deep=1.0, rem=1.5):
    chemin = dest / "sante" / "metriques" / "sleep_analysis.json"
    existant = json.loads(chemin.read_text()) if chemin.exists() else {"name": "sleep_analysis", "units": "hr", "data": []}
    existant["data"].append({"date": date, "sleepEnd": fin, "core": core, "deep": deep, "rem": rem, "awake": 0.5})
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(existant))


def seance(dest, nom_fichier, id, fin, **extra):
    chemin = dest / "sante" / "seances" / nom_fichier
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"id": id, "name": "Course", "end": fin, **extra}))


def test_reveil_signale_une_seule_fois_par_nuit(tmp_path):
    nuit(tmp_path, "2026-10-25 00:00:00 +0100", "2026-10-25 07:12:00 +0100")
    assert evenements.detecter(tmp_path, MAINTENANT) == [
        {"type": "reveil", "nuit": "2026-10-25", "fin": "2026-10-25 07:12:00 +0100", "sommeil_h": 7.5}]
    assert evenements.detecter(tmp_path, MAINTENANT) == []


def test_nuit_ancienne_ignoree_a_la_premiere_synchro(tmp_path):
    nuit(tmp_path, "2026-10-24 00:00:00 +0200", "2026-10-24 07:00:00 +0200")
    assert evenements.detecter(tmp_path, MAINTENANT) == []


def test_nuit_suivante_signalee(tmp_path):
    nuit(tmp_path, "2026-10-24 00:00:00 +0200", "2026-10-24 06:50:00 +0200")
    evenements.detecter(tmp_path, datetime.fromisoformat("2026-10-24T07:00:00+02:00"))
    nuit(tmp_path, "2026-10-25 00:00:00 +0100", "2026-10-25 07:12:00 +0100")
    assert [e["nuit"] for e in evenements.detecter(tmp_path, MAINTENANT)] == ["2026-10-25"]


def test_seance_terminee_signalee_une_fois(tmp_path):
    seance(tmp_path, "2026-10-25-W1.json", "W1", "2026-10-25 07:30:00 +0100", prevu_id="2026-10-25-facile")
    seance(tmp_path, "2026-10-20-W0.json", "W0", "2026-10-20 19:00:00 +0200")
    assert evenements.detecter(tmp_path, MAINTENANT) == [
        {"type": "seance", "id": "W1", "nom": "Course", "fin": "2026-10-25 07:30:00 +0100", "prevu_id": "2026-10-25-facile"}]
    assert evenements.detecter(tmp_path, MAINTENANT) == []


def test_fichiers_illisibles_ignores(tmp_path):
    (tmp_path / "sante" / "metriques").mkdir(parents=True)
    (tmp_path / "sante" / "metriques" / "sleep_analysis.json").write_text("{pas du json")
    seance(tmp_path, "2026-10-25-W1.json", "W1", "pas une date")
    assert evenements.detecter(tmp_path, MAINTENANT) == []


def test_declencher_passe_l_evenement_a_la_commande(tmp_path):
    sortie = tmp_path / "recu.json"
    script = f"import os, pathlib; pathlib.Path({str(sortie)!r}).write_text(os.environ['RELAY_EVENEMENT'])"
    evenements.declencher(f"{sys.executable} -c \"{script}\"", [{"type": "reveil", "nuit": "2026-10-25"}], journal=lambda m: None)
    for _ in range(50):
        if sortie.exists() and sortie.read_text():
            break
        time.sleep(0.1)
    assert json.loads(sortie.read_text()) == {"type": "reveil", "nuit": "2026-10-25"}
