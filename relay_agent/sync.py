"""`sync` : tire les blobs modifiés, les déchiffre, les range dans dest/ au format que le coaching lit déjà.
Le client ne supprime jamais un fichier local : dest/ est l'archive, le relais un tampon."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import fusion
from .client import Relais

ETAT_SYNC = Path(".relay") / "sync.json"


@dataclass
class Rapport:
    blobs_lus: int = 0
    blobs_ignores: list[str] = field(default_factory=list)


def _ecrire(chemin: Path, contenu: bytes) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(chemin.suffix + ".tmp")
    tmp.write_bytes(contenu)
    tmp.replace(chemin)


def _charger_json(chemin: Path):
    try:
        return json.loads(chemin.read_text()) if chemin.exists() else None
    except ValueError:
        return None


def _ranger(dest: Path, nom: str, clair: bytes) -> None:
    if nom.startswith("metriques/"):
        _, metrique, _ = nom.split("/", 2)
        cible = dest / "sante" / "metriques" / f"{metrique}.json"
        fusionne = fusion.fusionner_metrique(_charger_json(cible), json.loads(clair))
        _ecrire(cible, json.dumps(fusionne, ensure_ascii=False).encode())
    elif nom.startswith("seances/"):
        seance = json.loads(clair)
        prevu = _charger_json(dest / "coach" / "prevu.json") or {}
        fusion.apparier(seance, prevu.get("seances", []) if isinstance(prevu, dict) else [])
        _ecrire(dest / "sante" / "seances" / fusion.nom_fichier_seance(nom), json.dumps(seance, ensure_ascii=False).encode())
    elif nom == "etat.json":
        _ecrire(dest / "sante" / "etat.json", clair)
    elif nom == "prevu.json":
        _ecrire(dest / "coach" / "prevu.json", clair)
    else:
        raise ValueError(f"blob inattendu : {nom}")


def synchroniser(relais: Relais, dest: Path, journal=print) -> Rapport:
    dest = Path(dest)
    rapport = Rapport()
    etat = _charger_json(dest / ETAT_SYNC) or {}
    connus: dict[str, float] = etat.get("maj", {}) if isinstance(etat.get("maj"), dict) else {}
    distants = relais.lister()
    # prevu.json d'abord : l'appariement des séances s'appuie dessus
    distants.sort(key=lambda b: (b["nom"] != "prevu.json", b["nom"]))
    for b in distants:
        nom, maj = b["nom"], b["maj"]
        if connus.get(nom) == maj:
            continue
        try:
            clair = relais.lire(nom)
            if clair is None:
                continue
            _ranger(dest, nom, clair)
        except ValueError as e:
            rapport.blobs_ignores.append(nom)
            journal(f"ignoré {nom} : {e}")
            continue
        connus[nom] = maj
        rapport.blobs_lus += 1
    _ecrire(dest / ETAT_SYNC, json.dumps({"maj": connus}).encode())
    journal(f"synchro : {rapport.blobs_lus} blob(s) lu(s), {len(rapport.blobs_ignores)} ignoré(s)")
    return rapport
