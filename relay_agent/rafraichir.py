"""Demande au relais de réveiller l'iPhone et d'attendre sa synchro ; même dictionnaire que le client v1."""

from .client import AbonnementRequis, Injoignable, Refus, Relais


def demander(relais: Relais) -> dict:
    try:
        code, corps = relais.rafraichir()
        return {"http": code, "corps": corps, "erreur": None}
    except AbonnementRequis as e:
        return {"http": 402, "corps": None, "erreur": str(e)}
    except Refus as e:
        return {"http": e.code, "corps": None, "erreur": e.status}
    except Injoignable as e:
        return {"http": 0, "corps": None, "erreur": str(e)}
