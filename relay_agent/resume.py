"""Résumé santé (porté de resume-sante.py v1, texte identique) : sommeil, récupération, activité, nutrition,
poids, dépense estimée et séances récentes, calculés ici plutôt que par le modèle. Lit les fichiers que `sync`
écrit dans workspace/ (sante/, coach/nutrition.md). La réponse du rafraîchissement, si elle est fournie, nourrit
la ligne de fraîcheur : un chiffre se dit toujours avec son heure."""

import json
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

KJ_PER_KCAL = 4.184
KCAL_PER_KG = 7700
# Jours de nutrition saisis sur 28 pour estimer la dépense : seuil conservateur, un jour saisi peut
# quand même manquer des repas, et l'apport sous-estimé fait sous-estimer la dépense.
MIN_INTAKE_DAYS = 25
END_OF_DAY = "23:59"  # un point capté avant cette heure (hors agrégat 00:00:00) ne couvre pas toute la journée
PARIS = ZoneInfo("Europe/Paris")


def resume(workspace: Path, maintenant: datetime, aujourd_hui: date, reponse_rafraichissement: dict | None = None) -> str:
    WORKSPACE = Path(workspace)
    SANTE = WORKSPACE / "sante"
    NOW = maintenant.astimezone(PARIS)
    TODAY = aujourd_hui

    def daily(name):
        """{date: mesure} d'une métrique ; si plusieurs sources le même jour, la plus grande valeur."""
        path = SANTE / "metriques" / f"{name}.json"
        if not path.exists():
            return {}
        days = {}
        for p in json.loads(path.read_text())["data"]:
            day = date.fromisoformat(p["date"][:10])
            value = p.get("totalSleep", p.get("qty"))
            if value is not None and (day not in days or value > days[day].get("totalSleep", days[day].get("qty"))):
                days[day] = p
        return days


    def qty(days, factor=1.0):
        return {d: p["qty"] / factor for d, p in days.items()}


    def capture_time(days, d):
        """Heure (HH:MM) de la dernière capture si le point du jour d est partiel, sinon None.
        Les agrégats journaliers sont horodatés 00:00:00 ; une autre heure est celle de la capture."""
        p = days.get(d)
        hour = p["date"][11:19] if p else ""
        return hour[:5] if hour and hour != "00:00:00" and hour[:5] < END_OF_DAY else None


    def partial_label(days_list, d):
        """(libellé de capture partielle, {index des métriques partielles}) pour le jour d."""
        hours = {i: h for i, days in enumerate(days_list) if (h := capture_time(days, d))}
        if not hours:
            return "", set()
        return f" (capture partielle, dernière à {max(hours.values())})", set(hours)


    def at_least(text, partial):
        return f"au moins {text}" if partial else text


    def window(values, n, end=TODAY):
        return [v for d, v in values.items() if end - timedelta(days=n) < d <= end]


    def partial_days(days, n, end=TODAY):
        """Jours de la fenêtre dont le point est une capture partielle (une tranche, pas un total journalier)."""
        return [d for d in sorted(days) if end - timedelta(days=n) < d <= end and capture_time(days, d)]


    def full_avg(days, values, n, end=TODAY):
        """Moyenne de la fenêtre, ou None si un de ses points est partiel : elle mélangerait tranches et totaux."""
        return None if partial_days(days, n, end) else avg(window(values, n, end))


    def masked_note(days_list, n, end=TODAY):
        cut = sorted({d for days in days_list for d in partial_days(days, n, end)})
        return (f" (moyenne non calculée : capture partielle le {', '.join(f'{d:%d/%m}' for d in cut)}, "
                f"des tranches et non des totaux journaliers)") if cut else ""


    def fmt(x, digits=0):
        return "?" if x is None else f"{x:.{digits}f}".replace(".", ",")


    def avg(values):
        return mean(values) if values else None


    def deviation(value, baseline):
        if value is None or not baseline:
            return ""
        return f" ({(value - baseline) / baseline * 100:+.0f} % vs moyenne 28 j : {fmt(baseline)})"


    def slope_per_day(points):
        """Pente (kg/jour) de la droite des moindres carrés sur [(date, kg)]."""
        xs = [(d - points[0][0]).days for d, _ in points]
        ys = [v for _, v in points]
        mx, my = mean(xs), mean(ys)
        den = sum((x - mx) ** 2 for x in xs)
        return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den if den else None


    def targets():
        path = WORKSPACE / "coach" / "nutrition.md"
        match = path.exists() and re.search(
            r"Cibles\s*:\s*(\d+)\s*kcal,\s*(\d+)\s*g prot\w*,\s*(\d+)\s*g gluc\w*,\s*(\d+)\s*g lip\w*", path.read_text())
        return tuple(int(x) for x in match.groups()) if match else None


    def last_day(values):
        return max(values) if values else None


    def quand(horodatage, suite=""):
        """« 18:42 (il y a 28 min) », avec « le JJ/MM » si ce n'est pas aujourd'hui ; « jamais » sans horodatage."""
        if not horodatage:
            return "jamais"
        try:
            d = datetime.strptime(horodatage, "%Y-%m-%d %H:%M:%S %z").astimezone(PARIS)
        except (TypeError, ValueError):
            return "date illisible"
        minutes = (NOW - d).total_seconds() / 60
        age = (f"il y a {minutes:.0f} min" if minutes < 60 else f"il y a {minutes / 60:.0f} h" if minutes < 24 * 60
               else f"il y a {minutes / 1440:.0f} j")
        return f"{d:%H:%M}" + (f" le {d:%d/%m}" if d.date() != NOW.date() else "") + f" ({age}{suite})"


    def fraicheur(reponse):
        """Lignes sur la dernière synchro de l'app Relay et le dernier échantillon par type (sante/etat.json)."""
        etat = (SANTE / "etat.json")
        if not etat.exists():
            return []
        try:
            etat = json.loads(etat.read_text())
            assert isinstance(etat, dict)
        except (ValueError, AssertionError):
            return [f"Il est {NOW:%H:%M}. État de l'app Relay illisible (sante/etat.json) : dis-le à Julien."]
        if reponse is None:
            suite = ""
        elif reponse.get("http") == 200 and (reponse.get("corps") or {}).get("rafraichi"):
            suite = ", rafraîchie à la demande"
        elif reponse.get("http") == 200:
            suite = ""
        elif reponse.get("http") == 504:
            suite = " ; l'iPhone n'a pas répondu au réveil"
        else:
            suite = " ; rafraîchissement indisponible"
        latest = etat.get("latest") if isinstance(etat.get("latest"), dict) else {}
        return [f"Il est {NOW:%H:%M}. Dernière synchro de l'app Relay : {quand(etat.get('synced_at'), suite)}.",
                "Dernier échantillon connu par type : " + ", ".join(
                    f"{label} {quand(latest.get(cle))}" for cle, label in (
                        ("step_count", "pas"), ("dietary_energy", "repas"), ("weight_body_mass", "pesée"),
                        ("sleep_analysis", "sommeil"), ("workouts", "séance"), ("heart_rate_variability", "VFC"))) + ".",
                "Les totaux du jour s'arrêtent à ces heures-là : ne parle pas d'une journée comme finie si le dernier échantillon est vieux."]




    lines = [f"# Résumé santé ({TODAY.isoformat()}, calculé par relay-agent)"]

    files = list((SANTE / "metriques").glob("*.json"))
    if files:
        received = datetime.fromtimestamp(max(f.stat().st_mtime for f in files), ZoneInfo("Europe/Paris"))
        hours = (time.time() - received.timestamp()) / 3600
        alert = f" ⚠️ RIEN REÇU DEPUIS {hours:.0f} H : les chiffres ci-dessous peuvent être incomplets." if hours > 24 else ""
        lines.append(f"Dernier envoi reçu : {received:%Y-%m-%d %H:%M}.{alert}")
    else:
        lines.append("⚠️ Aucune donnée de santé reçue.")
    lines += fraicheur(reponse_rafraichissement)

    sleep = daily("sleep_analysis")
    if sleep:
        d = last_day(sleep)
        p = sleep[d]
        lines.append(f"Sommeil (nuit du {d - timedelta(days=1):%d/%m} au {d:%d/%m}) : {fmt(p.get('totalSleep'), 1)} h "
                     f"dont profond {fmt(p.get('deep'), 1)} h, paradoxal {fmt(p.get('rem'), 1)} h ; "
                     f"moyenne 7 j : {fmt(avg(window({k: v['totalSleep'] for k, v in sleep.items()}, 7)), 1)} h.")

    for name, label, unit in (("heart_rate_variability", "Variabilité cardiaque", "ms"),
                              ("resting_heart_rate", "Fréquence cardiaque au repos", "bpm")):
        values = qty(daily(name))
        if values:
            d = last_day(values)
            baseline = avg(window(values, 28, d - timedelta(days=1)))
            lines.append(f"{label} ({d:%d/%m}) : {fmt(values[d])} {unit}{deviation(values[d], baseline)}.")

    steps_days, active_days = daily("step_count"), daily("active_energy")
    steps, active = qty(steps_days), qty(active_days, KJ_PER_KCAL)
    for d in (TODAY - timedelta(days=1), TODAY):
        if d in steps or d in active:
            if d == TODAY:
                lines.append(f"Activité {d:%d/%m} (journée en cours) : {fmt(steps.get(d))} pas, {fmt(active.get(d))} kcal actives.")
                continue
            label, cut = partial_label((steps_days, active_days), d)
            lines.append(f"Activité {d:%d/%m}{label} : {at_least(fmt(steps.get(d)), 0 in cut)} pas, "
                         f"{at_least(fmt(active.get(d)), 1 in cut)} kcal actives{' ; total final inconnu' if cut else ''}.")
    yesterday = TODAY - timedelta(days=1)
    lines.append(f"Activité moyenne sur les 7 jours jusqu'à hier : {fmt(full_avg(steps_days, steps, 7, yesterday))} pas, "
                 f"{fmt(full_avg(active_days, active, 7, yesterday))} kcal actives"
                 f"{masked_note((steps_days, active_days), 7, yesterday)}.")

    intake_days = daily("dietary_energy")
    macro_days = {k: daily(k) for k in ("protein", "carbohydrates", "total_fat")}
    intake = qty(intake_days, KJ_PER_KCAL)
    macros = {k: qty(v) for k, v in macro_days.items()}
    goal = targets()
    lines.append("Cibles (coach/nutrition.md) : " + (f"{goal[0]} kcal, {goal[1]} g protéines, {goal[2]} g glucides, {goal[3]} g lipides."
                                                     if goal else "aucune, la mise en place n'est pas faite."))
    for d in (TODAY - timedelta(days=1), TODAY):
        if d in intake:
            if d == TODAY:
                label, cut = " (journée en cours)", set()
            else:
                label, cut = partial_label((intake_days, *macro_days.values()), d)
            lines.append(f"Nutrition {d:%d/%m}{label} : {at_least(fmt(intake[d]), 0 in cut)} kcal, "
                         f"{at_least(fmt(macros['protein'].get(d)), 1 in cut)} g protéines, "
                         f"{at_least(fmt(macros['carbohydrates'].get(d)), 2 in cut)} g glucides, "
                         f"{at_least(fmt(macros['total_fat'].get(d)), 3 in cut)} g lipides{' ; total final inconnu' if cut else ''}.")
    logged = window(intake, 7, yesterday)
    lines.append(f"Nutrition moyenne sur les jours saisis parmi les 7 jusqu'à hier ({len(logged)}/7) : "
                 f"{fmt(full_avg(intake_days, intake, 7, yesterday))} kcal, "
                 f"{fmt(full_avg(macro_days['protein'], macros['protein'], 7, yesterday))} g protéines"
                 f"{masked_note((intake_days, macro_days['protein']), 7, yesterday)}.")

    weight_days = daily("weight_body_mass")
    weights = sorted(qty(weight_days).items())
    recent = [(d, w) for d, w in weights if d > TODAY - timedelta(days=28)]
    if weights:
        d, w = weights[-1]
        lines.append(f"Poids : dernière pesée {fmt(w, 1)} kg le {d:%d/%m} ; "
                     f"moyenne 7 j : {fmt(avg([v for k, v in weights if k > TODAY - timedelta(days=7)]), 1)} kg ; "
                     f"{len(recent)} pesée(s) sur 28 j.")
    slope = slope_per_day(recent) if len(recent) >= 3 and (recent[-1][0] - recent[0][0]).days >= 14 else None
    if slope is not None:
        lines.append(f"Tendance du poids sur 28 j : {'+' if slope >= 0 else ''}{fmt(slope * 7, 2)} kg/semaine.")
    intake_28 = window(intake, 28, yesterday)
    cut_intake, cut_weight = partial_days(intake_days, 28, yesterday), partial_days(weight_days, 28)
    if cut_intake or cut_weight:
        cut = ", ".join(f"{label} le {', '.join(f'{d:%d/%m}' for d in ds)}"
                        for label, ds in (("nutrition", cut_intake), ("poids", cut_weight)) if ds)
        lines.append(f"Dépense estimée : masquée, capture partielle dans la fenêtre de 28 j ({cut}) ; "
                     f"l'apport moyen mélangerait des tranches et des journées entières.")
    elif len(intake_28) < MIN_INTAKE_DAYS:
        lines.append(f"Dépense non estimable : journal nutrition incomplet ({len(intake_28)}/28 jours saisis, "
                     f"il en faut au moins {MIN_INTAKE_DAYS}).")
    elif slope is not None:
        lines.append(f"Dépense estimée (apport moyen 28 j − variation de poids) : environ {fmt(mean(intake_28) - slope * KCAL_PER_KG)} kcal/jour "
                     f"({len(intake_28)}/28 jours saisis ; sous-estimée si des repas manquent au journal).")
    else:
        lines.append("Dépense estimée : pas assez de données (il faut 3 pesées sur au moins 14 jours).")

    workouts = sorted(f for f in (SANTE / "seances").glob("*.json") if f.name[:10] >= (TODAY - timedelta(days=7)).isoformat())
    lines.append(f"Séances des 7 derniers jours ({len(workouts)}) :" if workouts else "Séances des 7 derniers jours : aucune reçue.")
    for f in workouts:
        w = json.loads(f.read_text())
        extra = []
        if isinstance(w.get("distance"), dict):
            extra.append(f"{fmt(w['distance'].get('qty'), 1)} {w['distance'].get('units', '')}")
        if isinstance(w.get("avgHeartRate"), dict):
            extra.append(f"FC moy. {fmt(w['avgHeartRate'].get('qty'))}")
        source = w.get("source", {}).get("name", "?") if isinstance(w.get("source"), dict) else w.get("source", "?")
        prevue = f" prévue : {w['prevu_nom']}" if w.get("prevu_nom") else ""
        lines.append(f"- {w.get('start', '')[:16]} {w.get('name', '?')} : {fmt((w.get('duration') or 0) / 60)} min"
                     f"{', ' + ', '.join(extra) if extra else ''} ({source}){prevue} [seances/{f.name}]")

    return "\n".join(lines)
