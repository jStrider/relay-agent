"""Client HTTP du relais : chiffre avant de déposer, déchiffre après avoir lu, traduit les codes en exceptions."""

import json

import httpx

from . import chiffrement
from .phrase import Identite


class Injoignable(Exception):
    """Le relais ne répond pas (réseau, DNS, délai)."""


class AbonnementRequis(Exception):
    """Le relais répond 402 : la fonction demandée est réservée aux abonnés."""


class Refus(Exception):
    def __init__(self, code: int, status: str):
        super().__init__(f"HTTP {code} : {status}")
        self.code, self.status = code, status


class Relais:
    def __init__(self, url: str, identite: Identite, delai: float = 30.0):
        self.identite = identite
        self._http = httpx.Client(base_url=url.rstrip("/"), headers={"Authorization": f"Bearer {identite.jeton}"}, timeout=delai)

    def _requete(self, methode: str, chemin: str, **kw) -> httpx.Response:
        try:
            rep = self._http.request(methode, chemin, **kw)
        except httpx.HTTPError as e:
            raise Injoignable(f"relais injoignable : {type(e).__name__}") from None
        if rep.status_code == 402:
            raise AbonnementRequis("abonnement requis sur le relais")
        if rep.status_code >= 400 and rep.status_code != 404:
            try:
                status = rep.json().get("status", "")
            except ValueError:
                status = ""
            raise Refus(rep.status_code, status)
        return rep

    def lister(self, depuis: float | None = None) -> list[dict]:
        return self._requete("GET", "/blobs", params={"depuis": depuis} if depuis else None).json()

    def lire(self, nom: str) -> bytes | None:
        rep = self._requete("GET", f"/blobs/{nom}")
        if rep.status_code == 404:
            return None
        return chiffrement.dechiffrer(self.identite.cle, self.identite.id, nom, rep.content)

    def deposer(self, nom: str, clair: bytes) -> float:
        blob = chiffrement.chiffrer(self.identite.cle, self.identite.id, nom, clair)
        return self._requete("PUT", f"/blobs/{nom}", content=blob, headers={"Content-Type": "application/octet-stream"}).json()["maj"]

    def retirer(self, nom: str) -> bool:
        return self._requete("DELETE", f"/blobs/{nom}").status_code == 204

    def rafraichir(self) -> tuple[int, dict]:
        try:
            rep = self._http.post("/rafraichir", timeout=60)
        except httpx.HTTPError as e:
            raise Injoignable(f"relais injoignable : {type(e).__name__}") from None
        if rep.status_code == 402:
            raise AbonnementRequis("abonnement requis sur le relais")
        try:
            corps = rep.json()
        except ValueError:
            corps = {"status": "réponse illisible"}
        return rep.status_code, corps
