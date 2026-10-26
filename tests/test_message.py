import base64
import json

import pytest

from relay_agent import chiffrement, client
from relay_agent.phrase import Identite
from tests.faux_relais import FauxRelais

IDENTITE = Identite("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "a" * 43, bytes(range(32)))


@pytest.fixture
def relais():
    f = FauxRelais()
    yield f
    f.arreter()


def dechiffrer(chiffre):
    blob = base64.urlsafe_b64decode(chiffre + "=" * (-len(chiffre) % 4))
    return json.loads(chiffrement.dechiffrer(IDENTITE.cle, IDENTITE.id, "message", blob))


def test_message_chiffre_lie_au_compte(relais):
    client.Relais(relais.url, IDENTITE).envoyer_message("Bien joué ce matin", titre="Hermes")
    (chiffre,) = relais.messages
    assert "joué" not in chiffre
    assert dechiffrer(chiffre) == {"texte": "Bien joué ce matin", "titre": "Hermes"}


def test_message_vide_ou_trop_long_refuse(relais):
    r = client.Relais(relais.url, IDENTITE)
    for texte in ("  ", "é" * 1001):
        with pytest.raises(ValueError):
            r.envoyer_message(texte)
    assert relais.messages == []


def test_message_sans_abonnement(relais):
    relais.abonne = False
    with pytest.raises(client.AbonnementRequis):
        client.Relais(relais.url, IDENTITE).envoyer_message("x")
