"""Appairage par code court : l'agent ouvre une session sur le relais avec l'engagement (SHA-256) d'une clé X25519
éphémère, l'app pose sa clé, puis l'agent révèle la sienne et l'app vérifie qu'elle tient l'engagement ; les deux
dérivent la même clé et le même code à six chiffres, l'utilisateur compare les codes et l'app dépose la phrase
chiffrée. Le relais ne voit que des clés publiques et du chiffré. L'engagement l'oblige à choisir la clé qu'il
présenterait à l'agent sans connaître celle de l'agent : il ne peut plus chercher par force brute deux échanges
qui donnent le même code."""

import base64
import hashlib
import os
import stat
import time
from pathlib import Path

import httpx
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def engagement(cle_publique: bytes) -> str:
    """SHA-256 de la clé publique brute (32 octets), en base64url sans remplissage."""
    return _b64(hashlib.sha256(cle_publique).digest())


def deriver(secret: bytes, session: str) -> tuple[bytes, str]:
    """(clé de transport 32 octets, code à six chiffres) depuis le secret X25519 et la session."""
    def hk(info: str, n: int) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=n, salt=session.encode(), info=info.encode()).derive(secret)
    code = int.from_bytes(hk("relay-appairage-code", 4), "big") % 1_000_000
    return hk("relay-appairage-cle", 32), f"{code:06d}"


def chiffrer_identite(cle: bytes, session: str, phrase: str, nonce: bytes | None = None) -> bytes:
    nonce = nonce or os.urandom(12)
    return nonce + AESGCM(cle).encrypt(nonce, phrase.encode(), session.encode())


def dechiffrer_identite(cle: bytes, session: str, blob: bytes) -> str:
    try:
        return AESGCM(cle).decrypt(blob[:12], blob[12:], session.encode()).decode()
    except (InvalidTag, UnicodeDecodeError, ValueError):
        raise ValueError("identité illisible : session ou clé différente") from None


def enregistrer_phrase(phrase: str, chemin: Path, forcer: bool = False) -> None:
    """Écrit la phrase en 0600 ; refuse d'écraser une phrase existante sans `forcer`."""
    chemin = Path(chemin)
    if chemin.exists() and not forcer:
        raise FileExistsError(f"{chemin} existe déjà : relance avec --oui pour la remplacer")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(phrase)
    tmp.chmod(stat.S_IRUSR | stat.S_IWUSR)
    tmp.replace(chemin)


class Appairage:
    def __init__(self, url: str):
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=30)
        self._privee = X25519PrivateKey.generate()
        self.session: str | None = None
        self.code: str | None = None
        self._cle: bytes | None = None

    def ouvrir(self) -> str:
        rep = self._http.post("/appairages", json={"engagement": engagement(self._privee.public_key().public_bytes_raw())})
        rep.raise_for_status()
        self.session = rep.json()["session"]
        return self.session

    def _etat(self) -> dict:
        rep = self._http.get(f"/appairages/{self.session}")
        if rep.status_code == 404:
            raise TimeoutError("session d'appairage expirée ou fermée")
        rep.raise_for_status()
        return rep.json()

    def attendre_cle_app(self, delai: float = 600) -> str:
        """Dès que l'app a posé sa clé : révèle celle de l'agent, puis rend le code à six chiffres ; TimeoutError sinon."""
        fin = time.time() + delai
        while time.time() < fin:
            etat = self._etat()
            if etat.get("cle_publique_app"):
                rep = self._http.put(f"/appairages/{self.session}/agent", json={"cle_publique_agent": _b64(self._privee.public_key().public_bytes_raw())})
                if rep.status_code == 404:
                    raise TimeoutError("session d'appairage expirée ou fermée")
                rep.raise_for_status()
                secret = self._privee.exchange(X25519PublicKey.from_public_bytes(_unb64(etat["cle_publique_app"])))
                self._cle, self.code = deriver(secret, self.session)
                return self.code
            time.sleep(0.5)
        raise TimeoutError("l'app n'a pas rejoint la session à temps")

    def attendre_identite(self, delai: float = 600) -> str:
        """La phrase déchiffrée dès que l'app l'a déposée ; la session est fermée ensuite."""
        if self._cle is None:
            raise RuntimeError("attendre_cle_app d'abord")
        fin = time.time() + delai
        while time.time() < fin:
            etat = self._etat()
            if etat.get("identite_chiffree"):
                phrase = dechiffrer_identite(self._cle, self.session, _unb64(etat["identite_chiffree"]))
                self._http.delete(f"/appairages/{self.session}")
                return phrase
            time.sleep(0.5)
        raise TimeoutError("l'app n'a pas confirmé à temps")
