"""Fusion des mois reçus en fichiers Health Auto Export, et appariement prévu/réalisé (porté du serveur v1)."""


def _cle(point: dict) -> tuple[str, str]:
    return (str(point.get("date") or "")[:10], str(point.get("source") or ""))


def fusionner_metrique(existant: dict | None, mois: dict) -> dict:
    """Un point par (jour, source), le reçu remplace l'existant, tri par date. Idempotent."""
    resultat = {"name": mois.get("name") or (existant or {}).get("name"), "units": mois.get("units") or (existant or {}).get("units"), "data": []}
    points = {_cle(p): p for p in (existant or {}).get("data", [])}
    points.update({_cle(p): p for p in mois.get("data", [])})
    resultat["data"] = sorted(points.values(), key=lambda p: str(p.get("date") or ""))
    return resultat


def _heure(texte: str) -> int:
    try:
        return int(texte[11:13]) * 60 + int(texte[14:16])
    except (TypeError, ValueError, IndexError):
        return 0


def apparier(seance: dict, prevues: list) -> None:
    """Une course du jour d'une séance prévue reçoit l'identifiant et le nom de la plus proche en heure."""
    if seance.get("name") != "Course":
        return
    debut = str(seance.get("start") or "")
    du_jour = [p for p in prevues if isinstance(p, dict) and str(p.get("date") or "")[:10] == debut[:10]]
    if du_jour:
        p = min(du_jour, key=lambda p: abs(_heure(str(p.get("date") or "")) - _heure(debut)))
        seance["prevu_id"], seance["prevu_nom"] = p.get("id"), p.get("nom")


def nom_fichier_seance(nom_blob: str) -> str:
    return nom_blob.split("/", 1)[1]
