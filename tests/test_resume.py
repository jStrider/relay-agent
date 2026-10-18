"""Tests de relay_agent.resume (le résumé santé v1 porté en fonction) sur des jeux minimaux : veille complète (agrégat 00:00:00 ou capture à 23:59),
veille partielle (capture à 18:50, fichiers au mtime récent), et fenêtre de 28 jours complète ou contenant
des captures partielles (moyennes 7 j et dépense estimée). Lancer : uv run pytest -q"""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from relay_agent import resume

TODAY = "2026-10-15"
PARIS = ZoneInfo("Europe/Paris")


def calculer(tmp, maintenant=None, reponse=None):
    return resume.resume(Path(tmp), maintenant or datetime.now(PARIS), date.fromisoformat(TODAY), reponse).splitlines()

# kJ = kcal × 4,184
DAY_VALUES = {"step_count": 5715, "active_energy": 601 * 4.184, "dietary_energy": 1137 * 4.184,
              "protein": 58, "carbohydrates": 120, "total_fat": 40}
# Perte linéaire de 0,5 kg/semaine sur 14 jours : dépense = 1137 + 0,5 / 7 × 7700 = 1687 kcal/jour
WEIGHTS = {"2026-09-22": 96.0, "2026-09-29": 95.5, "2026-10-06": 95.0}


def run(points):
    """Écrit {métrique: {"AAAA-MM-JJ HH:MM:SS": valeur}}, puis renvoie les lignes du résumé du 15/10."""
    with tempfile.TemporaryDirectory() as tmp:
        metriques = Path(tmp) / "sante" / "metriques"
        metriques.mkdir(parents=True)
        (Path(tmp) / "sante" / "seances").mkdir()
        for name, values in points.items():
            (metriques / f"{name}.json").write_text(json.dumps(
                {"name": name, "data": [{"date": f"{t} +0200", "qty": v, "source": ""} for t, v in values.items()]}))
        return calculer(tmp)


def run_day(hour_by_metric):
    """Un seul point du 14/10 par métrique, à l'heure donnée (00:00:00 par défaut)."""
    return run({name: {f"2026-10-14 {hour_by_metric.get(name, '00:00:00')}": value}
                for name, value in DAY_VALUES.items()})


NUTRITION = ("dietary_energy", "protein", "carbohydrates", "total_fat")


def run_window(partial=(), nutrition_days=28):
    """28 jours de données (17/09 au 14/10) et 3 pesées, tous en agrégats 00:00:00, sauf les
    (métrique, jour) de partial, captés à 18:50:44 avec un tiers de la valeur (une tranche).
    Seuls les nutrition_days jours les plus récents ont une saisie de nutrition."""
    points = {name: {} for name in DAY_VALUES}
    for i in range(1, 29):
        day = (date.fromisoformat(TODAY) - timedelta(days=i)).isoformat()
        for name, value in DAY_VALUES.items():
            if name in NUTRITION and i > nutrition_days:
                continue
            if (name, day) in partial:
                points[name][f"{day} 18:50:44"] = value / 3
            else:
                points[name][f"{day} 00:00:00"] = value
    points["weight_body_mass"] = {f"{day} {'18:50:44' if ('weight_body_mass', day) in partial else '00:00:00'}": w
                                  for day, w in WEIGHTS.items()}
    return run(points)


def line(lines, prefix):
    return next(l for l in lines if l.startswith(prefix))


class VeilleSeule(unittest.TestCase):
    def test_veille_partielle(self):
        lines = run_day({n: "18:50:44" for n in DAY_VALUES})
        print("\n--- veille partielle ---\n" + "\n".join(lines))
        self.assertEqual(line(lines, "Activité 14/10"),
                         "Activité 14/10 (capture partielle, dernière à 18:50) : au moins 5715 pas, "
                         "au moins 601 kcal actives ; total final inconnu.")
        self.assertEqual(line(lines, "Nutrition 14/10"),
                         "Nutrition 14/10 (capture partielle, dernière à 18:50) : au moins 1137 kcal, "
                         "au moins 58 g protéines, au moins 120 g glucides, au moins 40 g lipides ; total final inconnu.")
        # mtime récent : pas d'alerte de fraîcheur, et pourtant la veille reste marquée partielle
        self.assertNotIn("RIEN REÇU", line(lines, "Dernier envoi"))

    def test_veille_complete_agregat(self):
        lines = run_day({})
        print("\n--- veille complète (00:00:00) ---\n" + "\n".join(lines))
        self.assertEqual(line(lines, "Activité 14/10"), "Activité 14/10 : 5715 pas, 601 kcal actives.")
        self.assertEqual(line(lines, "Nutrition 14/10"),
                         "Nutrition 14/10 : 1137 kcal, 58 g protéines, 120 g glucides, 40 g lipides.")

    def test_veille_complete_fin_de_journee(self):
        lines = run_day({n: "23:59:30" for n in DAY_VALUES})
        self.assertEqual(line(lines, "Activité 14/10"), "Activité 14/10 : 5715 pas, 601 kcal actives.")

    def test_une_seule_metrique_partielle(self):
        lines = run_day({"step_count": "18:50:44"})
        self.assertEqual(line(lines, "Activité 14/10"),
                         "Activité 14/10 (capture partielle, dernière à 18:50) : au moins 5715 pas, "
                         "601 kcal actives ; total final inconnu.")
        self.assertEqual(line(lines, "Nutrition 14/10"),
                         "Nutrition 14/10 : 1137 kcal, 58 g protéines, 120 g glucides, 40 g lipides.")


class Fenetre(unittest.TestCase):
    def test_fenetre_complete(self):
        lines = run_window()
        print("\n--- fenêtre complète ---\n" + "\n".join(lines))
        self.assertEqual(line(lines, "Activité moyenne"),
                         "Activité moyenne sur les 7 jours jusqu'à hier : 5715 pas, 601 kcal actives.")
        self.assertEqual(line(lines, "Nutrition moyenne"),
                         "Nutrition moyenne sur les jours saisis parmi les 7 jusqu'à hier (7/7) : 1137 kcal, 58 g protéines.")
        self.assertEqual(line(lines, "Tendance du poids"), "Tendance du poids sur 28 j : -0,50 kg/semaine.")
        self.assertEqual(line(lines, "Dépense estimée"),
                         "Dépense estimée (apport moyen 28 j − variation de poids) : environ 1687 kcal/jour "
                         "(28/28 jours saisis ; sous-estimée si des repas manquent au journal).")

    def test_nutrition_14_sur_28_non_estimable(self):
        """Cas réel après export manuel complet : 14/28 jours saisis, 3 pesées sur 14 jours."""
        lines = run_window(nutrition_days=14)
        print("\n--- nutrition 14/28 ---\n" + "\n".join(lines))
        self.assertEqual(line(lines, "Dépense"),
                         "Dépense non estimable : journal nutrition incomplet (14/28 jours saisis, il en faut au moins 25).")
        self.assertEqual(line(lines, "Tendance du poids"), "Tendance du poids sur 28 j : -0,50 kg/semaine.")
        self.assertEqual(line(lines, "Nutrition moyenne"),
                         "Nutrition moyenne sur les jours saisis parmi les 7 jusqu'à hier (7/7) : 1137 kcal, 58 g protéines.")

    def test_nutrition_24_sur_28_non_estimable(self):
        lines = run_window(nutrition_days=24)
        self.assertEqual(line(lines, "Dépense"),
                         "Dépense non estimable : journal nutrition incomplet (24/28 jours saisis, il en faut au moins 25).")

    def test_nutrition_25_sur_28_estimee(self):
        lines = run_window(nutrition_days=25)
        self.assertEqual(line(lines, "Dépense"),
                         "Dépense estimée (apport moyen 28 j − variation de poids) : environ 1687 kcal/jour "
                         "(25/28 jours saisis ; sous-estimée si des repas manquent au journal).")

    def test_tranche_masque_avant_le_seuil(self):
        """Avec 14/28 jours saisis, une tranche dans la fenêtre garde le message de masquage existant."""
        lines = run_window({("dietary_energy", "2026-10-12")}, nutrition_days=14)
        self.assertIn("masquée, capture partielle dans la fenêtre de 28 j (nutrition le 12/10)", line(lines, "Dépense"))

    def test_captures_partielles(self):
        """Cas réel du 15/10 : tranches du 11 au 14/10 (pas et énergie active), du 12 au 14/10 (nutrition)."""
        partial = ({(m, f"2026-10-{d}") for m in ("step_count", "active_energy") for d in (11, 12, 13, 14)}
                   | {(m, f"2026-10-{d}") for m in DAY_VALUES if m not in ("step_count", "active_energy")
                      for d in (12, 13, 14)})
        lines = run_window(partial)
        print("\n--- captures partielles ---\n" + "\n".join(lines))
        self.assertEqual(line(lines, "Activité moyenne"),
                         "Activité moyenne sur les 7 jours jusqu'à hier : ? pas, ? kcal actives (moyenne non calculée : "
                         "capture partielle le 11/10, 12/10, 13/10, 14/10, des tranches et non des totaux journaliers).")
        self.assertEqual(line(lines, "Nutrition moyenne"),
                         "Nutrition moyenne sur les jours saisis parmi les 7 jusqu'à hier (7/7) : ? kcal, ? g protéines "
                         "(moyenne non calculée : capture partielle le 12/10, 13/10, 14/10, "
                         "des tranches et non des totaux journaliers).")
        self.assertEqual(line(lines, "Dépense estimée"),
                         "Dépense estimée : masquée, capture partielle dans la fenêtre de 28 j "
                         "(nutrition le 12/10, 13/10, 14/10) ; l'apport moyen mélangerait des tranches et des journées entières.")
        # Les autres sorties restent : veille marquée partielle, tendance du poids inchangée
        self.assertTrue(line(lines, "Activité 14/10").startswith("Activité 14/10 (capture partielle, dernière à 18:50)"))
        self.assertEqual(line(lines, "Tendance du poids"), "Tendance du poids sur 28 j : -0,50 kg/semaine.")

    def test_une_metrique_partielle_masque_seulement_sa_moyenne(self):
        lines = run_window({("step_count", "2026-10-11")})
        self.assertEqual(line(lines, "Activité moyenne"),
                         "Activité moyenne sur les 7 jours jusqu'à hier : ? pas, 601 kcal actives (moyenne non calculée : "
                         "capture partielle le 11/10, des tranches et non des totaux journaliers).")
        self.assertEqual(line(lines, "Activité 14/10"), "Activité 14/10 : 5715 pas, 601 kcal actives.")
        self.assertTrue(line(lines, "Dépense").startswith("Dépense estimée (apport moyen"))

    def test_nutrition_partielle_hors_7_jours(self):
        """Une tranche le 01/10 garde la moyenne 7 j mais masque la dépense (fenêtre de 28 j)."""
        lines = run_window({("dietary_energy", "2026-10-01")})
        self.assertEqual(line(lines, "Nutrition moyenne"),
                         "Nutrition moyenne sur les jours saisis parmi les 7 jusqu'à hier (7/7) : 1137 kcal, 58 g protéines.")
        self.assertIn("masquée, capture partielle dans la fenêtre de 28 j (nutrition le 01/10)", line(lines, "Dépense estimée"))

    def test_poids_partiel_masque_la_depense(self):
        lines = run_window({("weight_body_mass", "2026-10-06")})
        self.assertIn("masquée, capture partielle dans la fenêtre de 28 j (poids le 06/10)", line(lines, "Dépense estimée"))
        self.assertEqual(line(lines, "Activité moyenne"),
                         "Activité moyenne sur les 7 jours jusqu'à hier : 5715 pas, 601 kcal actives.")




# --- Fraîcheur (app Relay) et séance prévue ---------------------------------------------------

MAINTENANT = datetime.strptime("2026-10-15 19:10", "%Y-%m-%d %H:%M").replace(tzinfo=PARIS)


def run_coach(etat=None, reponse_client=None, sans_rafraichir=False, seance=None):
    """Résumé sur un dossier temporaire avec un sante/etat.json optionnel, une séance optionnelle et la réponse
    du rafraîchissement passée directement (None si --sans-rafraichir)."""
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "sante" / "metriques").mkdir(parents=True)
        (Path(tmp) / "sante" / "seances").mkdir()
        if etat is not None:
            (Path(tmp) / "sante" / "etat.json").write_text(json.dumps(etat))
        if seance is not None:
            (Path(tmp) / "sante" / "seances" / f"{seance['start'][:10]}-{seance['id']}.json").write_text(json.dumps(seance))
        reponse = None if sans_rafraichir else (reponse_client or {"http": 0, "corps": None, "erreur": "faux"})
        return calculer(tmp, MAINTENANT, reponse)


ETAT = {"synced_at": "2026-10-15 18:42:00 +0200", "received_at": "2026-10-15 18:42:01 +0200",
        "latest": {"step_count": "2026-10-15 17:42:00 +0200", "dietary_energy": "2026-10-15 13:05:00 +0200",
                   "weight_body_mass": "2026-10-14 07:30:00 +0200", "sleep_analysis": "2026-10-15 07:11:00 +0200"}}


class Fraicheur(unittest.TestCase):
    def test_sans_etat_pas_de_ligne_fraicheur(self):
        lines = run_coach(sans_rafraichir=True)
        self.assertFalse(any(l.startswith("Il est ") for l in lines))

    def test_etat_affiche_heures_et_ages(self):
        lines = run_coach(etat=ETAT, sans_rafraichir=True)
        self.assertEqual(line(lines, "Il est"), "Il est 19:10. Dernière synchro de l'app Relay : 18:42 (il y a 28 min).")
        self.assertEqual(line(lines, "Dernier échantillon"),
                         "Dernier échantillon connu par type : pas 17:42 (il y a 1 h), repas 13:05 (il y a 6 h), "
                         "pesée 07:30 le 14/10 (il y a 1 j), sommeil 07:11 (il y a 12 h), séance jamais, VFC jamais.")
        self.assertIn("Les totaux du jour s'arrêtent à ces heures-là", "\n".join(lines))

    def test_synced_at_en_utc_converti(self):
        lines = run_coach(etat={**ETAT, "synced_at": "2026-10-15 16:42:00 +0000"}, sans_rafraichir=True)
        self.assertTrue(line(lines, "Il est").startswith("Il est 19:10. Dernière synchro de l'app Relay : 18:42 "))

    def test_rafraichi_a_la_demande(self):
        frais = {**ETAT, "synced_at": "2026-10-15 19:09:50 +0200"}
        lines = run_coach(etat=frais, reponse_client={"http": 200, "corps": {"rafraichi": True, "etat": frais, "status": "rafraîchi"}, "erreur": None})
        self.assertEqual(line(lines, "Il est"), "Il est 19:10. Dernière synchro de l'app Relay : 19:09 (il y a 0 min, rafraîchie à la demande).")

    def test_iphone_sans_reponse(self):
        lines = run_coach(etat=ETAT, reponse_client={"http": 504, "corps": {"rafraichi": False, "etat": ETAT, "status": "pas de réponse"}, "erreur": None})
        self.assertEqual(line(lines, "Il est"), "Il est 19:10. Dernière synchro de l'app Relay : 18:42 (il y a 28 min ; l'iPhone n'a pas répondu au réveil).")

    def test_client_injoignable(self):
        lines = run_coach(etat=ETAT, reponse_client={"http": 0, "corps": None, "erreur": "refusé"})
        self.assertEqual(line(lines, "Il est"), "Il est 19:10. Dernière synchro de l'app Relay : 18:42 (il y a 28 min ; rafraîchissement indisponible).")

    def test_sans_rafraichir_n_appelle_pas_le_client(self):
        lines = run_coach(etat=ETAT, reponse_client={"http": 200, "corps": {"rafraichi": True, "etat": ETAT}, "erreur": None}, sans_rafraichir=True)
        self.assertEqual(line(lines, "Il est"), "Il est 19:10. Dernière synchro de l'app Relay : 18:42 (il y a 28 min).")


class EtatAbime(unittest.TestCase):
    def test_horodatage_illisible_n_empeche_pas_le_resume(self):
        lines = run_coach(etat={**ETAT, "latest": {"step_count": 12345, "dietary_energy": "hier"}}, sans_rafraichir=True)
        self.assertIn("pas date illisible", line(lines, "Dernier échantillon"))
        self.assertTrue(any(l.startswith("Séances des 7 derniers jours") for l in lines))

    def test_etat_json_invalide_n_empeche_pas_le_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "sante" / "metriques").mkdir(parents=True)
            (Path(tmp) / "sante" / "seances").mkdir()
            (Path(tmp) / "sante" / "etat.json").write_text("{")
            texte = "\n".join(calculer(tmp, MAINTENANT, None))
        self.assertIn("État de l'app Relay illisible", texte)
        self.assertIn("Séances des 7 derniers jours", texte)


class SeancePrevue(unittest.TestCase):
    def test_course_appariee_affiche_prevue(self):
        seance = {"id": "W1", "name": "Course", "start": "2026-10-14 18:34:02 +0200", "end": "2026-10-14 19:10:00 +0200",
                  "duration": 2158, "source": {"name": "Strava", "identifier": "com.strava"},
                  "prevu_id": "2026-10-14-frac-6x3", "prevu_nom": "Frac 6 × 3 min"}
        lines = run_coach(sans_rafraichir=True, seance=seance)
        self.assertEqual(line(lines, "- 2026-10-14 18:34"), "- 2026-10-14 18:34 Course : 36 min (Strava) prévue : Frac 6 × 3 min [seances/2026-10-14-W1.json]")
