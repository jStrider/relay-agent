"""Séances planifiées pour la montre, course, vélo, marche, rando ou natation (contrat prevu.json), avec validation.
Chaque changement est écrit en local puis déposé chiffré sur le relais ; si le relais refuse, le local est restauré."""

import json
import re
from datetime import datetime
from pathlib import Path

from . import fusion
from .client import Relais


class Validation(ValueError):
    """Argument refusé : le message dit pourquoi, pour l'agent qui l'a produit."""


SPORTS = fusion.NOMS_SANTE  # sports que l'app sait envoyer sur la montre
ALLURE_GUIDEE = {"course", "velo"}  # ailleurs, la montre refuse l'alerte d'allure ; la fréquence cardiaque marche partout


def _allure(texte: str) -> dict:
    def secondes(v):
        if ":" in v:
            m, s = v.split(":")
            return int(m) * 60 + int(s)
        return int(v)
    try:
        a, b = (secondes(v) for v in texte.split("-"))
    except ValueError:
        raise Validation(f"allure illisible : {texte!r} (attendu 265-280 ou 4:25-4:40)") from None
    return {"min_s_km": min(a, b), "max_s_km": max(a, b)}


def _vitesse(texte: str) -> dict:
    """« 25-30kmh » en allure (s/km), le format que lit l'app."""
    try:
        a, b = (float(v.replace(",", ".")) for v in texte[:-3].split("-"))
        return {"min_s_km": round(3600 / max(a, b)), "max_s_km": round(3600 / min(a, b))}
    except (ValueError, ZeroDivisionError):
        raise Validation(f"vitesse illisible : {texte!r} (attendu 25-30kmh)") from None


def _etape(texte: str, sport: str = "course") -> dict:
    m = re.fullmatch(r"(effort|recup):(\d+)(m?)(?:@(\S+))?", texte)
    if not m:
        raise Validation(f"étape illisible dans le bloc : {texte!r} (attendu effort:180@265-280, recup:120, effort:400m@4:10-4:20, effort:600@fc140-155, effort:600@25-30kmh)")
    genre, valeur, metres, cible = m.groups()
    e = {"type": genre, "distance_m" if metres else "duree_s": int(valeur)}
    if not cible:
        return e
    fc = re.fullmatch(r"fc(\d+)-(\d+)", cible)
    if fc:
        a, b = int(fc.group(1)), int(fc.group(2))
        e["fc"] = {"min": min(a, b), "max": max(a, b)}
        return e
    if sport not in ALLURE_GUIDEE:
        raise Validation(f"la montre ne guide l'allure qu'en course et à vélo, pas en {sport} : vise une fréquence cardiaque (@fc120-140)")
    e["allure"] = _vitesse(cible) if cible.endswith("kmh") else _allure(cible)
    return e


def _bloc(texte: str, sport: str = "course") -> dict:
    parts = texte.split()
    m = re.fullmatch(r"(\d+)x", parts[0]) if parts else None
    if not m or len(parts) < 2:
        raise Validation(f"bloc illisible : {texte!r} (attendu « 6x effort:180@265-280 recup:120 »)")
    return {"repetitions": int(m.group(1)), "etapes": [_etape(p, sport) for p in parts[1:]]}


def _chemin(dest: Path) -> Path:
    return Path(dest) / "coach" / "prevu.json"


def lister(dest: Path) -> list[dict]:
    chemin = _chemin(dest)
    if not chemin.exists():
        return []
    try:
        seances = json.loads(chemin.read_text()).get("seances", [])
    except (ValueError, AttributeError):
        raise Validation(f"{chemin} illisible : corrige-le ou supprime-le") from None
    return sorted((s for s in seances if isinstance(s, dict)), key=lambda s: str(s.get("date", "")))


def formater(seances: list[dict]) -> str:
    return "\n".join(f"{s['id']} {s['date']} {s['nom']}" for s in seances) or "aucune séance prévue"


def _enregistrer(dest: Path, relais: Relais, seances: list[dict]) -> list[dict]:
    """Local puis relais ; si le relais refuse, le fichier local revient à son état d'avant."""
    chemin = _chemin(dest)
    avant = chemin.read_bytes() if chemin.exists() else None
    contenu = json.dumps({"seances": sorted(seances, key=lambda s: s["date"])}, ensure_ascii=False, indent=1).encode()
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_bytes(contenu)
    tmp.replace(chemin)
    try:
        relais.deposer("prevu.json", contenu)
    except Exception:
        if avant is None:
            chemin.unlink(missing_ok=True)
        else:
            chemin.write_bytes(avant)
        raise
    return lister(dest)


def ajouter(dest: Path, relais: Relais, id: str, nom: str, date: str, blocs: list[str],
            echauffement: int = 0, retour_calme: int = 0, maintenant: datetime | None = None,
            sport: str = "course", lieu: str = "exterieur") -> list[dict]:
    if sport not in SPORTS:
        raise Validation(f"sport inconnu : {sport!r} (attendu {', '.join(SPORTS)})")
    if lieu not in ("exterieur", "interieur"):
        raise Validation(f"lieu inconnu : {lieu!r} (attendu exterieur, ou interieur pour tapis, home trainer ou piscine)")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*", id):
        raise Validation("id attendu au format AAAA-MM-JJ-<slug en minuscules>, par exemple 2026-10-21-frac-6x3")
    try:
        quand = datetime.fromisoformat(date)
    except ValueError:
        raise Validation(f"date illisible : {date!r} (attendu 2026-10-21T18:30:00+02:00)") from None
    if quand.tzinfo is None:
        raise Validation("la date doit porter son décalage horaire, par exemple +02:00")
    if quand <= (maintenant or datetime.now().astimezone()):
        raise Validation(f"date passée : {date} ; une séance se planifie dans le futur")
    s = {"id": id, "nom": nom, "date": quand.isoformat(timespec="seconds")}  # sans fraction : l'app la refuserait
    if sport != "course":  # valeurs par défaut omises : une course garde le format, et son empreinte, d'avant les sports
        s["sport"] = sport
    if lieu != "exterieur":
        s["lieu"] = lieu
    if echauffement:
        s["echauffement"] = {"duree_s": int(echauffement)}
    s["blocs"] = [_bloc(b, sport) for b in blocs]
    if retour_calme:
        s["retour_calme"] = {"duree_s": int(retour_calme)}
    return _enregistrer(dest, relais, [x for x in lister(dest) if x.get("id") != id] + [s])


def retirer(dest: Path, relais: Relais, id: str) -> list[dict]:
    seances = lister(dest)
    if not any(s.get("id") == id for s in seances):
        raise Validation(f"id inconnu : {id}")
    return _enregistrer(dest, relais, [s for s in seances if s.get("id") != id])


def purger(dest: Path, relais: Relais, maintenant: datetime | None = None) -> list[dict]:
    maintenant = maintenant or datetime.now().astimezone()
    return _enregistrer(dest, relais, [s for s in lister(dest) if datetime.fromisoformat(s["date"]) > maintenant])
