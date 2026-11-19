"""Tests des grèves ATC, sans réseau. Calendriers et relevés SYNTHÉTIQUES
(zone AA, aéroports AAAA / AAZZ / BBBB), sauf le dernier test qui lit le vrai
calendrier data/strikes.yaml."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ec_detector.engine import (AUCUNE, CONTINUER, EC_PROBABLE, INCERTAIN,
                                MISE_EN_ATTENTE, RELECTURE_JURISTE, decide, load_rules)
from ec_detector.models import Flight, MetarObs
from ec_detector.strikes import StrikeCalendar, load_strikes

ROOT = Path(__file__).resolve().parent.parent
RULES = load_rules(ROOT / "config" / "rules.yaml")
T0 = datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc)   # départ prévu
SOURCE = "https://example.org/greve-test"


def flight(dep="AAAA", arr="BBBB", delay_minutes=240, day_offset=0):
    t = T0 + timedelta(days=day_offset)
    return Flight("TEST", dep, arr,
                  scheduled_departure=t,
                  scheduled_arrival=t + timedelta(hours=2),
                  actual_departure=t + timedelta(minutes=delay_minutes),
                  actual_arrival=t + timedelta(hours=2, minutes=delay_minutes))


def calm_fetch(airport, start, end):
    """Météo calme, relevés toutes les 30 min."""
    out, t = [], start
    while t <= end:
        out.append(MetarObs(airport, t, 8, None, 9999, (), None, f"TEST {t:%H%M}"))
        t += timedelta(minutes=30)
    return out


def calendar(*strikes, zones=("AA", "BB")):
    return StrikeCalendar.from_dict({
        "version": "test",
        "coverage": [{"zone": z, "from": "2026-03-01T00:00:00Z", "to": "2026-04-01T00:00:00Z",
                      "checked_by": "test"} for z in zones],
        "strikes": list(strikes),
    })


def strike(status="confirmed", airports=("AAAA",)):
    return {"id": "AA-ATC-TEST", "status": status, "zone": "AA",
            "confirmed_airports": list(airports),
            "start": "2026-03-10T00:00:00Z", "end": "2026-03-11T00:00:00Z",
            "unions": ["SYND-TEST"], "sources": [SOURCE]}


def run(f, cal):
    return decide("t", f, RULES, fetch=calm_fetch, strikes=cal)


# ---------- Décisions ----------

def test_greve_confirmee_a_l_aeroport_ec_probable_avec_preuve():
    d = run(flight(), calendar(strike()))
    assert d.status == EC_PROBABLE and d.ec_type == "GREVE_ATC"
    assert d.ec_types == ["GREVE_ATC"]
    assert d.confidence == RULES["confidence"]["ec_strike_confirmed"]
    assert d.fully_explained and d.action == MISE_EN_ATTENTE
    ev = [e for e in d.evidence if e["source"] == "CALENDRIER_GREVES"]
    assert ev and ev[0]["strike"]["id"] == "AA-ATC-TEST"
    assert ev[0]["strike"]["sources"] == [SOURCE]
    assert ev[0]["airport"] == "AAAA" and ev[0]["rule_id"] == "strike.confirmed_airport"
    assert d.strike_calendar_version == "test"


def test_greve_dans_la_zone_aeroport_non_confirme_incertain():
    # AAZZ est dans la zone AA, mais aucune source ne le cite comme touché.
    d = run(flight(dep="AAZZ"), calendar(strike()))
    assert d.status == INCERTAIN and d.action == RELECTURE_JURISTE
    assert any("aéroport non confirmé" in r for r in d.reasons)


def test_preavis_non_confirme_incertain():
    d = run(flight(), calendar(strike(status="announced")))
    assert d.status == INCERTAIN
    assert any("préavis non confirmé" in r for r in d.reasons)


def test_greve_annulee_ignoree():
    d = run(flight(), calendar(strike(status="cancelled")))
    assert d.status == AUCUNE and d.action == CONTINUER


def test_hors_couverture_jamais_aucune():
    # Zone BB non vérifiée : l'absence de grève n'est pas établie.
    d = run(flight(), calendar(zones=("AA",)))
    assert d.status == INCERTAIN
    assert any("non vérifié pour BBBB" in r for r in d.reasons)


def test_periode_non_couverte_incertain():
    d = run(flight(day_offset=60), calendar())   # mai 2026, couverture = mars
    assert d.status == INCERTAIN


def test_couvert_sans_greve_aucune():
    d = run(flight(), calendar())
    assert d.status == AUCUNE and d.action == CONTINUER
    assert any("Aucune grève ATC" in r for r in d.reasons)


def test_greve_un_autre_jour_sans_effet():
    d = run(flight(day_offset=2), calendar(strike()))
    assert d.status == AUCUNE


def test_calendrier_illisible_jamais_aucune(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "strikes.yaml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)          # le calendrier par défaut est vide
    d = decide("t", flight(), RULES, fetch=calm_fetch)
    assert d.status == INCERTAIN
    assert d.strike_check["error"] and d.strike_calendar_version is None


def test_greve_masque_pas_par_trou_meteo():
    # Données météo incomplètes, mais grève confirmée : la grève l'emporte.
    def no_data(airport, start, end):
        return []
    d = decide("t", flight(), RULES, fetch=no_data, strikes=calendar(strike()))
    assert d.status == EC_PROBABLE and d.ec_type == "GREVE_ATC"


def test_meteo_et_greve_les_deux_types_retenus():
    def storm(airport, start, end):
        return [MetarObs(o.station, o.observed_at, 30, 60, 9999, (), None, o.raw)
                if airport == "AAAA" and abs((o.observed_at - T0).total_seconds()) <= 3600
                else o for o in calm_fetch(airport, start, end)]
    d = decide("t", flight(), RULES, fetch=storm, strikes=calendar(strike()))
    assert d.status == EC_PROBABLE
    assert set(d.ec_types) == {"METEO", "GREVE_ATC"}
    assert d.ec_type == d.ec_types[0]
    assert {e["source"] for e in d.evidence} == {"METAR", "CALENDRIER_GREVES"}


# ---------- Calendrier ----------

def test_greve_sans_source_refusee():
    bad = strike()
    bad["sources"] = []
    with pytest.raises(ValueError, match="aucune source"):
        calendar(bad)


def test_heure_sans_fuseau_refusee():
    bad = strike()
    bad["start"] = "2026-03-10T00:00:00"
    with pytest.raises(ValueError, match="fuseau"):
        calendar(bad)


def test_vrai_calendrier_valide_et_source():
    cal = load_strikes(ROOT / "data" / "strikes.yaml")
    assert cal.version and cal.coverage
    for s in cal.strikes:
        assert s.sources and all(u.startswith("https://") for u in s.sources)
