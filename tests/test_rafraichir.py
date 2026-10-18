import pytest

from relay_agent import client, rafraichir
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))


def test_rafraichir_dict_v1():
    f = FauxRelais(rafraichir=(504, {"rafraichi": False, "status": "pas de réponse"}))
    try:
        d = rafraichir.demander(client.Relais(f.url, IDENTITE))
    finally:
        f.arreter()
    assert d == {"http": 504, "corps": {"rafraichi": False, "status": "pas de réponse"}, "erreur": None}


def test_rafraichir_injoignable_http_0():
    d = rafraichir.demander(client.Relais("http://127.0.0.1:1", IDENTITE))
    assert d["http"] == 0 and d["corps"] is None and d["erreur"]


def test_rafraichir_402():
    f = FauxRelais(abonne=False)
    try:
        d = rafraichir.demander(client.Relais(f.url, IDENTITE))
    finally:
        f.arreter()
    assert d["http"] == 402 and "abonnement" in d["erreur"]
