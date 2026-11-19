"""Tests de l'API, sans réseau : relevés et calendrier SYNTHÉTIQUES."""

from datetime import timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ec_detector.api import create_app  # noqa: E402
from ec_detector.engine import load_rules  # noqa: E402
from ec_detector.models import MetarObs  # noqa: E402
from ec_detector.strikes import StrikeCalendar  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules(ROOT / "config" / "rules.yaml")
CAL = StrikeCalendar.from_dict({
    "version": "test",
    "coverage": [{"zone": z, "from": "2026-01-01T00:00:00Z", "to": "2027-01-01T00:00:00Z",
                  "checked_by": "test"} for z in ("AA", "BB")],
    "strikes": [],
})
FLIGHT = {"number": "T1", "departure": "AAAA", "arrival": "BBBB",
          "scheduled_departure": "2026-03-10T09:00:00Z", "scheduled_arrival": "2026-03-10T11:00:00Z",
          "actual_departure": "2026-03-10T13:00:00Z", "actual_arrival": "2026-03-10T15:00:00Z"}


def calm(airport, start, end):
    out, t = [], start
    while t <= end:
        out.append(MetarObs(airport, t, 8, None, 9999, (), None, "TEST"))
        t += timedelta(minutes=30)
    return out


@pytest.fixture
def client(tmp_path):
    case = tmp_path / "demo_1.yaml"
    case.write_text(
        "case_id: demo_1\ndescription: test\nflight:\n"
        + "".join(f"  {k}: \"{v}\"\n" for k, v in FLIGHT.items())
        + "expected:\n  status: AUCUNE\n  ec_type: null\nsources: []\nverification: {}\n",
        encoding="utf-8")
    return TestClient(create_app(RULES, CAL, fetch=calm, cases_dir=tmp_path))


def test_decide_meme_json_que_le_moteur(client):
    r = client.post("/api/decide", json={"case_id": "x", "flight": FLIGHT})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "AUCUNE" and d["action"] == "CONTINUER"
    assert d["rules_version"] == RULES["version"] and d["strike_calendar_version"] == "test"


def test_heure_sans_fuseau_422_avec_message(client):
    bad = dict(FLIGHT, scheduled_departure="2026-03-10T09:00")
    r = client.post("/api/decide", json={"case_id": "x", "flight": bad})
    assert r.status_code == 422 and "fuseau" in r.json()["detail"]


def test_champ_manquant_422(client):
    bad = {k: v for k, v in FLIGHT.items() if k != "arrival"}
    assert client.post("/api/decide", json={"case_id": "x", "flight": bad}).status_code == 422


def test_batch(client):
    r = client.post("/api/decide/batch", json={"cases": [{"case_id": "a", "flight": FLIGHT},
                                                         {"case_id": "b", "flight": FLIGHT}]})
    assert [d["case_id"] for d in r.json()] == ["a", "b"]


def test_cases_sans_etiquette_et_evaluation(client):
    cases = client.get("/api/cases").json()
    assert cases[0]["case_id"] == "demo_1" and "expected" not in cases[0]
    ev = client.get("/api/evaluation").json()
    assert ev["score"]["n"] == 1 and ev["rows"][0]["outcome"] == "CORRECT"


def test_meta_et_page(client):
    m = client.get("/api/meta").json()
    assert m["compensation_threshold_minutes"] == 180 and m["strike_coverage"]
    assert "Détecteur" in client.get("/").text
    assert client.get("/static/app.js").status_code == 200
