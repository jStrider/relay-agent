import base64
import hashlib
import json
import os
import stat
import threading
import time
from pathlib import Path

import httpx
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


def test_engagement_vecteur():
    assert hashlib.sha256(bytes.fromhex(V["publique_agent"])).hexdigest() == V["engagement"]
    assert appairage.engagement(bytes.fromhex(V["publique_agent"])) == b64(V["engagement"])


def test_aad_autre_session():
    with pytest.raises(ValueError):
        appairage.dechiffrer_identite(bytes.fromhex(V["cle"]), "ABCDEFGH", bytes.fromhex(V["identite_chiffree"]))


def jouer_l_app(relais, session, phrase, delai=0.3):
    """Un faux iPhone, par le relais : lit l'engagement, pose sa clé, attend celle de l'agent, vérifie qu'elle tient
    l'engagement (sinon `relais.rejet_app`), calcule le code, dépose la phrase chiffrée."""
    def f():
        time.sleep(delai)
        http = httpx.Client(base_url=relais.url)
        engagement = http.get(f"/appairages/{session}").json()["engagement"]
        app = X25519PrivateKey.generate()
        http.put(f"/appairages/{session}/app", json={"cle_publique_app": appairage._b64(app.public_key().public_bytes_raw())})
        cle_agent = None
        while cle_agent is None:
            time.sleep(0.05)
            cle_agent = http.get(f"/appairages/{session}").json()["cle_publique_agent"]
        brute = appairage._unb64(cle_agent)
        if appairage._b64(hashlib.sha256(brute).digest()) != engagement:
            relais.rejet_app = True
            return
        cle, code = appairage.deriver(app.exchange(X25519PublicKey.from_public_bytes(brute)), session)
        relais.codes_app = code
        time.sleep(delai)
        http.put(f"/appairages/{session}/identite", json={"identite_chiffree": appairage._b64(appairage.chiffrer_identite(cle, session, phrase))})

    def g():
        try:
            f()
        except httpx.HTTPError:
            pass  # le test a fini avant le faux iPhone : le relais est arrêté
    threading.Thread(target=g, daemon=True).start()


def attendre(condition, delai=2):
    """L'agent a son code dès qu'il a révélé sa clé ; le faux iPhone a besoin d'un instant de plus pour le sien."""
    fin = time.time() + delai
    while not condition() and time.time() < fin:
        time.sleep(0.05)
    return condition()


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
    assert attendre(lambda: getattr(relais, "codes_app", None))
    assert code == relais.codes_app and len(code) == 6
    phrase = a.attendre_identite(delai=5)
    assert phrase == V["phrase"]
    chemin = tmp_path / "phrase"
    appairage.enregistrer_phrase(phrase, chemin)
    assert chemin.read_text() == phrase and stat.S_IMODE(chemin.stat().st_mode) == 0o600
    assert session not in relais.appairages  # fermée après lecture


def test_agent_ne_revele_sa_cle_qu_apres_celle_de_l_app(relais):
    a = appairage.Appairage(relais.url)
    session = a.ouvrir()
    assert relais.appairages[session]["agent"] is None
    jouer_l_app(relais, session, V["phrase"])
    a.attendre_cle_app(delai=5)
    poses = [chemin for methode, chemin in relais.requetes if methode == "PUT"]
    assert poses.index(f"/appairages/{session}/app") < poses.index(f"/appairages/{session}/agent")


def test_relais_substitue_la_cle_de_l_app_codes_differents(relais):
    relais.substituer = "app"
    a = appairage.Appairage(relais.url)
    session = a.ouvrir()
    jouer_l_app(relais, session, V["phrase"])
    code = a.attendre_cle_app(delai=5)
    assert attendre(lambda: getattr(relais, "codes_app", None))
    assert code != relais.codes_app
    with pytest.raises(ValueError):  # si l'utilisateur confirmait quand même, la phrase resterait illisible
        a.attendre_identite(delai=5)


def test_relais_substitue_la_cle_de_l_agent_l_app_rejette(relais):
    relais.substituer = "agent"
    a = appairage.Appairage(relais.url)
    session = a.ouvrir()
    jouer_l_app(relais, session, V["phrase"])
    a.attendre_cle_app(delai=5)
    assert attendre(lambda: getattr(relais, "rejet_app", False))
    assert not getattr(relais, "codes_app", None)


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
