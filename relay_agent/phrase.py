"""Phrase d'appairage `relay1:<id>:<jeton>:<cle>` : identité du compte et clé de chiffrement, qui ne doit
être lisible que de l'agent."""

import base64
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

CHEMIN_DEFAUT = Path.home() / ".config" / "relay" / "phrase"
URL_DEFAUT = "https://relay.example.invalid"  # remplacée par le relais de Julien dès que le domaine est connu


@dataclass(frozen=True)
class Identite:
    id: str
    jeton: str = field(repr=False)  # jamais dans une trace ni un journal
    cle: bytes = field(repr=False)


def analyser(texte: str) -> Identite:
    parts = texte.strip().split(":")
    if len(parts) != 4 or parts[0] != "relay1":
        raise ValueError("phrase d'appairage attendue au format relay1:<id>:<jeton>:<cle>")
    _, id, jeton, cle_b64 = parts
    if not re.fullmatch(r"[A-Z2-7]{26}", id) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", jeton):
        raise ValueError("identifiant ou jeton mal formé dans la phrase")
    try:
        cle = base64.urlsafe_b64decode(cle_b64 + "=" * (-len(cle_b64) % 4))
    except ValueError:
        raise ValueError("clé illisible dans la phrase") from None
    if len(cle) != 32:
        raise ValueError("la clé doit faire 32 octets")
    return Identite(id, jeton, cle)


def charger(env=os.environ, chemin: Path = CHEMIN_DEFAUT) -> Identite:
    """RELAY_PHRASE, sinon le fichier, qui doit être privé (ni groupe ni autres)."""
    if env.get("RELAY_PHRASE"):
        return analyser(env["RELAY_PHRASE"])
    chemin = Path(chemin)
    if not chemin.exists():
        raise ValueError(f"aucune phrase d'appairage : RELAY_PHRASE ou {chemin}")
    if stat.S_IMODE(chemin.stat().st_mode) & 0o077:
        raise PermissionError(f"{chemin} est lisible par d'autres utilisateurs : chmod 600")
    return analyser(chemin.read_text())


def url(env=os.environ) -> str:
    return env.get("RELAY_URL", URL_DEFAUT).rstrip("/")
