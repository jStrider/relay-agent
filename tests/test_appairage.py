import base64
import json
import os
import stat
import threading
import time
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey

from relay_agent import appairage
from tests.faux_relais import FauxRelais

V = json.loads((Path(__file__).parent.parent / "vecteurs" / "appairage.json").read_text())


def b64(h):
    return base64.urlsafe_b64encode(bytes.fromhex(h)).decode().rstrip("=")


def test_derivation_vecteur():
    agent = X25519PrivateKey.from_private_bytes(bytes.fromhex(V["privee_agent"]))
    secret = agent.exchange(X25519PublicKey.from_public_bytes(bytes.fromhex(V["publique_app"])))
    cle, code = appairage.deriver(secret, V["session"])
    assert cle.hex() == V["cle"] and code == V["code"]


def test_identite_vecteur():
    cle = bytes.fromhex(V["cle"])
    assert appairage.chiffrer_identite(cle, V["session"], V["phrase"], nonce=bytes.fromhex(V["nonce"])).hex() == V["identite_chiffree"]
    assert appairage.dechiffrer_identite(cle, V["session"], bytes.fromhex(V["identite_chiffree"])) == V["phrase"]


def test_aad_autre_session():
    with pytest.raises(ValueError):
        appairage.dechiffrer_identite(bytes.fromhex(V["cle"]), "ABCDEFGH", bytes.fromhex(V["identite_chiffree"]))


def jouer_l_app(relais, session, phrase, delai=0.3):
    """Un faux iPhone : lit la clé de l'agent, pose la sienne, calcule le code, dépose la phrase chiffrée."""
    def f():
        time.sleep(delai)
        s = relais.appairages[session]
        app = X25519PrivateKey.generate()
        s["app"] = base64.urlsafe_b64encode(app.public_key().public_bytes_raw()).decode().rstrip("=")
        secret = app.exchange(X25519PublicKey.from_public_bytes(base64.urlsafe_b64decode(s["agent"] + "=")))
        cle, code = appairage.deriver(secret, session)
        relais.codes_app = code
        time.sleep(delai)
        s["identite"] = base64.urlsafe_b64encode(appairage.chiffrer_identite(cle, session, phrase)).decode().rstrip("=")
    threading.Thread(target=f, daemon=True).start()


@pytest.fixture
def relais():
    f = FauxRelais()
    yield f
    f.arreter()


def test_relier_de_bout_en_bout(relais, tmp_path):
    a = appairage.Appairage(relais.url)
    session = a.ouvrir()
    assert session == "K7Q2M6XA"
    jouer_l_app(relais, session, V["phrase"])
    code = a.attendre_cle_app(delai=5)
    assert code == relais.codes_app and len(code) == 6
    phrase = a.attendre_identite(delai=5)
    assert phrase == V["phrase"]
    chemin = tmp_path / "phrase"
    appairage.enregistrer_phrase(phrase, chemin)
    assert chemin.read_text() == phrase and stat.S_IMODE(chemin.stat().st_mode) == 0o600
    assert session not in relais.appairages  # fermée après lecture


def test_attente_expire(relais):
    a = appairage.Appairage(relais.url)
    a.ouvrir()
    with pytest.raises(TimeoutError):
        a.attendre_cle_app(delai=0.6)


def test_enregistrer_refuse_d_ecraser_sans_forcer(tmp_path):
    chemin = tmp_path / "phrase"
    chemin.write_text("ancienne")
    with pytest.raises(FileExistsError):
        appairage.enregistrer_phrase("nouvelle", chemin)
    appairage.enregistrer_phrase("nouvelle", chemin, forcer=True)
    assert chemin.read_text() == "nouvelle"
