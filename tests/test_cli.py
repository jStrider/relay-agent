import json

import pytest

from relay_agent import cli
from tests.faux_relais import FauxRelais

PHRASE = "relay1:ABCDEFGHIJKLMNOPQRSTUVWXYZ:" + "a" * 43 + ":AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8"


@pytest.fixture
def relais():
    f = FauxRelais()
    yield f
    f.arreter()


def lancer(args, env, capsys):
    code = cli.main(args, env=env)
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def test_cli_sans_phrase_sort_en_2(tmp_path, capsys):
    code, out, err = lancer(["sync", "--dest", str(tmp_path)], {"RELAY_URL": "http://127.0.0.1:1", "HOME": str(tmp_path)}, capsys)
    assert code == 2 and "phrase" in err


def test_cli_sync_puis_resume(relais, tmp_path, capsys):
    env = {"RELAY_PHRASE": PHRASE, "RELAY_URL": relais.url}
    assert lancer(["sync", "--dest", str(tmp_path)], env, capsys)[0] == 0
    code, out, _ = lancer(["resume", "--dest", str(tmp_path), "--sans-rafraichir"], env, capsys)
    assert code == 0 and out.startswith("# Résumé santé")


def test_cli_seance_402_sort_en_4(relais, tmp_path, capsys):
    relais.abonne = False
    env = {"RELAY_PHRASE": PHRASE, "RELAY_URL": relais.url}
    code, out, err = lancer(["seance", "ajouter", "--id", "2099-01-01-a", "--nom", "A", "--date", "2099-01-01T10:00:00+01:00",
                             "--bloc", "1x effort:600", "--dest", str(tmp_path)], env, capsys)
    assert code == 4 and "abonnement" in err


def test_cli_seance_validation_sort_en_2(relais, tmp_path, capsys):
    env = {"RELAY_PHRASE": PHRASE, "RELAY_URL": relais.url}
    code, out, err = lancer(["seance", "ajouter", "--id", "x", "--nom", "A", "--date", "2099-01-01T10:00:00+01:00", "--bloc", "1x effort:600", "--dest", str(tmp_path)], env, capsys)
    assert code == 2 and "AAAA-MM-JJ" in err


def test_cli_injoignable_sort_en_3(tmp_path, capsys):
    code, out, err = lancer(["sync", "--dest", str(tmp_path)], {"RELAY_PHRASE": PHRASE, "RELAY_URL": "http://127.0.0.1:1"}, capsys)
    assert code == 3


def test_cli_rafraichir_imprime_le_dict(relais, tmp_path, capsys):
    code, out, _ = lancer(["rafraichir"], {"RELAY_PHRASE": PHRASE, "RELAY_URL": relais.url}, capsys)
    assert code == 0 and json.loads(out)["http"] == 200
