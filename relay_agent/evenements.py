"""Événements repérés après une synchro (réveil, séance terminée), chacun signalé une seule fois à une commande
choisie par l'agent : `--sur-evenement 'commande'` reçoit l'événement en JSON dans RELAY_EVENEMENT."""

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

ETAT = Path(".relay") / "evenements.json"
FENETRE = timedelta(hours=6)  # plus vieux, ce n'est plus une nouvelle : une première synchro ne réveille pas l'agent pour l'historique


def _lire(chemin: Path):
    try:
        return json.loads(chemin.read_text())
    except (OSError, ValueError):
        return None


def _date(texte) -> datetime | None:
    try:
        return datetime.strptime(str(texte), "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def _recent(quand: datetime | None, maintenant: datetime) -> bool:
    return quand is not None and timedelta(0) <= maintenant - quand <= FENETRE


def detecter(dest: Path, maintenant: datetime) -> list[dict]:
    """Nouveaux événements depuis la dernière détection ; l'état est mis à jour dans dest/.relay/evenements.json."""
    dest = Path(dest)
    etat = _lire(dest / ETAT) or {}
    vus = list(etat.get("seances", []))
    nouveaux = []
    sommeil = _lire(dest / "sante" / "metriques" / "sleep_analysis.json")
    nuits = [p for p in (sommeil or {}).get("data", []) if isinstance(p, dict) and _date(p.get("sleepEnd"))] if isinstance(sommeil, dict) else []
    if nuits:
        n = max(nuits, key=lambda p: _date(p["sleepEnd"]))
        cle = str(n.get("date"))[:10]
        if cle != etat.get("reveil") and _recent(_date(n["sleepEnd"]), maintenant):
            dort = sum(n.get(k) or 0 for k in ("core", "deep", "rem", "asleep"))
            nouveaux.append({"type": "reveil", "nuit": cle, "fin": n["sleepEnd"], "sommeil_h": round(dort, 1)})
            etat["reveil"] = cle
    veille = (maintenant - timedelta(days=1)).strftime("%Y-%m-%d")
    for f in sorted((dest / "sante" / "seances").glob("*.json")):
        if f.name[:10] < veille:
            continue
        s = _lire(f)
        if not isinstance(s, dict) or s.get("id") in vus or not _recent(_date(s.get("end")), maintenant):
            continue
        e = {"type": "seance", "id": s["id"], "nom": s.get("name"), "fin": s["end"]}
        if s.get("prevu_id"):
            e["prevu_id"] = s["prevu_id"]
        nouveaux.append(e)
        vus.append(s["id"])
    etat["seances"] = vus[-50:]
    (dest / ETAT).parent.mkdir(parents=True, exist_ok=True)
    (dest / ETAT).write_text(json.dumps(etat))
    return nouveaux


def declencher(commande: str, liste: list[dict], journal=print) -> None:
    """Lance la commande une fois par événement, sans l'attendre : l'agent peut mettre des minutes à répondre."""
    for e in liste:
        try:
            subprocess.Popen(commande, shell=True, env={**os.environ, "RELAY_EVENEMENT": json.dumps(e, ensure_ascii=False)},
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            journal(f"événement {e['type']} signalé")
        except OSError as err:
            journal(f"événement {e['type']} : commande impossible à lancer ({type(err).__name__})")
