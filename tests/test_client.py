import pytest

from relay_agent import client, chiffrement
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))


@pytest.fixture
def relais():
    f = FauxRelais()
    yield f
    f.arreter()


def test_deposer_chiffre_et_lire_dechiffre(relais):
    r = client.Relais(relais.url, IDENTITE)
    maj = r.deposer("etat.json", b'{"secret": "CLAIR"}')
    assert maj > 0
    assert b"CLAIR" not in relais.blobs["etat.json"][0]
    assert r.lire("etat.json") == b'{"secret": "CLAIR"}'
    assert [b["nom"] for b in r.lister()] == ["etat.json"]
    assert r.lister(depuis=maj + 1) == []
    assert r.retirer("etat.json") is True and r.retirer("etat.json") is False


def test_402_leve_abonnement_requis(relais):
    relais.abonne = False
    r = client.Relais(relais.url, IDENTITE)
    with pytest.raises(client.AbonnementRequis):
        r.deposer("prevu.json", b"{}")
    with pytest.raises(client.AbonnementRequis):
        r.rafraichir()


def test_injoignable():
    r = client.Relais("http://127.0.0.1:1", IDENTITE)
    with pytest.raises(client.Injoignable):
        r.lister()


def test_jeton_refuse(relais):
    r = client.Relais(relais.url, Identite(IDENTITE.id, "b" * 43, IDENTITE.cle))
    with pytest.raises(client.Refus) as e:
        r.lister()
    assert e.value.code == 401


def test_rafraichir_renvoie_code_et_corps(relais):
    relais.reponse_rafraichir = (504, {"rafraichi": False, "status": "pas de réponse"})
    code, corps = client.Relais(relais.url, IDENTITE).rafraichir()
    assert (code, corps["status"]) == (504, "pas de réponse")
