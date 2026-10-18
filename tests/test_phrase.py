import base64
import os

import pytest

from relay_agent import phrase

ID = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
JETON = "a" * 43
CLE = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
PHRASE = f"relay1:{ID}:{JETON}:{CLE}"


def test_phrase_valide():
    i = phrase.analyser(PHRASE)
    assert (i.id, i.jeton, i.cle) == (ID, JETON, bytes(range(32)))


def test_phrase_prefixe_faux():
    with pytest.raises(ValueError):
        phrase.analyser("relay2:" + PHRASE[7:])


def test_phrase_cle_trop_courte():
    with pytest.raises(ValueError):
        phrase.analyser(f"relay1:{ID}:{JETON}:AAAA")


def test_charger_depuis_env(tmp_path):
    assert phrase.charger(env={"RELAY_PHRASE": PHRASE}, chemin=tmp_path / "absent").id == ID


def test_charger_depuis_fichier_sur(tmp_path):
    f = tmp_path / "phrase"
    f.write_text(PHRASE + "\n")
    f.chmod(0o600)
    assert phrase.charger(env={}, chemin=f).jeton == JETON


def test_charger_fichier_trop_ouvert_refuse(tmp_path):
    f = tmp_path / "phrase"
    f.write_text(PHRASE)
    f.chmod(0o644)
    with pytest.raises(PermissionError):
        phrase.charger(env={}, chemin=f)


def test_charger_sans_phrase(tmp_path):
    with pytest.raises(ValueError):
        phrase.charger(env={}, chemin=tmp_path / "absent")


def test_url_par_defaut_et_env():
    assert phrase.url({}).startswith("https://")
    assert phrase.url({"RELAY_URL": "http://127.0.0.1:8780/"}) == "http://127.0.0.1:8780"


def test_repr_ne_montre_ni_jeton_ni_cle():
    i = phrase.analyser(PHRASE)
    assert JETON not in repr(i) and "cle=" not in repr(i) and ID in repr(i)
