"""Tests de weather.py, sans réseau.

ATTENTION : les relevés ci-dessous sont SYNTHÉTIQUES. Ils servent seulement
à tester la lecture du format CSV de l'IEM. Ce ne sont pas des données réelles.
"""

from datetime import date, datetime, timezone

import pytest

from ec_detector.weather import get_observations, parse_csv, fetch_day_csv

HEADER = ("station,valid,sknt,gust,vsby,wxcodes,skyc1,skyc2,skyc3,skyc4,"
          "skyl1,skyl2,skyl3,skyl4,metar\n")

SYNTHETIC_DAY_1 = HEADER + (
    "TEST,2030-01-01 22:00,10,,6.21,,FEW,,,,3000,,,,TEST SYNTHETIQUE 1\n"
    "TEST,2030-01-01 23:30,35,50,0.25,+SN BR,SCT,OVC,,,500,200,,,TEST SYNTHETIQUE 2\n"
)
SYNTHETIC_DAY_2 = HEADER + (
    "TEST,2030-01-02 00:30,5,,6.21,,,,,,,,,,TEST SYNTHETIQUE 3\n"
)


def _write_cache(tmp_path, day, text):
    path = tmp_path / "TEST" / f"{day}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_parse_csv_convertit_les_unites():
    obs = parse_csv(SYNTHETIC_DAY_1)
    assert len(obs) == 2

    calme, neige = obs
    assert calme.gust_kt is None                 # valeur absente -> None
    assert calme.ceiling_ft is None              # FEW ne fait pas un plafond
    assert neige.wind_kt == 35 and neige.gust_kt == 50
    assert neige.visibility_m == 402             # 0.25 mile -> 402 m
    assert neige.wx_codes == ("+SN", "BR")
    assert neige.ceiling_ft == 200               # plus basse couche OVC
    assert neige.observed_at.tzinfo == timezone.utc


def test_get_observations_lit_le_cache_et_filtre_la_fenetre(tmp_path):
    _write_cache(tmp_path, "2030-01-01", SYNTHETIC_DAY_1)
    _write_cache(tmp_path, "2030-01-02", SYNTHETIC_DAY_2)

    start = datetime(2030, 1, 1, 23, 0, tzinfo=timezone.utc)
    end = datetime(2030, 1, 2, 1, 0, tzinfo=timezone.utc)
    obs = get_observations("test", start, end, cache_dir=tmp_path)

    # La fenêtre traverse minuit : deux fichiers lus, le relevé de 22:00 exclu.
    assert [o.raw for o in obs] == ["TEST SYNTHETIQUE 2", "TEST SYNTHETIQUE 3"]


def test_heure_sans_fuseau_refusee(tmp_path):
    with pytest.raises(ValueError):
        get_observations("TEST", datetime(2030, 1, 1), datetime(2030, 1, 2),
                         cache_dir=tmp_path)


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    """Renvoie les réponses dans l'ordre ; la dernière est répétée."""
    def __init__(self, *responses):
        self.responses = [r if isinstance(r, _FakeResponse) else _FakeResponse(r)
                          for r in responses]
        self.calls = 0

    def get(self, url, params, timeout):
        resp = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return resp


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    """Les tests ne doivent pas attendre réellement."""
    monkeypatch.setattr("ec_detector.weather.time.sleep", lambda s: None)


def test_reponse_invalide_non_mise_en_cache(tmp_path):
    session = _FakeSession("Unknown station")
    with pytest.raises(ValueError):
        fetch_day_csv("TEST", date(2030, 1, 1), cache_dir=tmp_path, session=session)
    assert not (tmp_path / "TEST" / "2030-01-01.csv").exists()


def test_reponse_valide_mise_en_cache(tmp_path):
    session = _FakeSession(SYNTHETIC_DAY_1)
    fetch_day_csv("TEST", date(2030, 1, 1), cache_dir=tmp_path, session=session)
    assert (tmp_path / "TEST" / "2030-01-01.csv").exists()


def test_reessai_apres_429(tmp_path):
    session = _FakeSession(_FakeResponse("trop de requêtes", 429), SYNTHETIC_DAY_1)
    text = fetch_day_csv("TEST", date(2030, 1, 1), cache_dir=tmp_path, session=session)
    assert session.calls == 2
    assert text.startswith("station,")


def test_abandon_apres_trop_de_429(tmp_path):
    session = _FakeSession(_FakeResponse("trop de requêtes", 429))
    with pytest.raises(RuntimeError):
        fetch_day_csv("TEST", date(2030, 1, 1), cache_dir=tmp_path, session=session)
    assert not (tmp_path / "TEST" / "2030-01-01.csv").exists()