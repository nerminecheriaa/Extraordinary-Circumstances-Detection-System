"""Tests du moteur, sans réseau. Relevés SYNTHÉTIQUES (station TEST)."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ec_detector.engine import (AUCUNE, CONTINUER, EC_PROBABLE, INCERTAIN,
                                MISE_EN_ATTENTE, RELECTURE_JURISTE, decide, load_rules)
from ec_detector.models import Flight, MetarObs
from ec_detector.strikes import StrikeCalendar

RULES = load_rules(Path(__file__).resolve().parent.parent / "config" / "rules.yaml")
T0 = datetime(2026, 1, 10, 9, 0, tzinfo=timezone.utc)   # départ prévu

# Calendrier des grèves SYNTHÉTIQUE : zones AA et BB vérifiées, aucune grève.
COVERED = StrikeCalendar.from_dict({
    "version": "test",
    "coverage": [{"zone": z, "from": "2026-01-01T00:00:00Z", "to": "2028-01-01T00:00:00Z",
                  "checked_by": "test"} for z in ("AA", "BB")],
    "strikes": [],
})


def flight(delay_minutes=240):
    return Flight("TEST", "AAAA", "BBBB",
                  scheduled_departure=T0,
                  scheduled_arrival=T0 + timedelta(hours=2),
                  actual_departure=T0 + timedelta(minutes=delay_minutes),
                  actual_arrival=T0 + timedelta(hours=2, minutes=delay_minutes))


def fake_fetch(bad_airport=None, bad_hours=(), gust=60, every=30, skip_hours=()):
    """Relevés toutes les `every` minutes. Rafales `gust` à `bad_airport`
    pendant les heures `bad_hours` (décalage par rapport à T0)."""
    def fetch(airport, start, end):
        out, t = [], start
        while t <= end:
            hour = int((t - T0).total_seconds() // 3600)
            if hour not in skip_hours:
                g = gust if airport == bad_airport and hour in bad_hours else None
                out.append(MetarObs(airport, t, 8, g, 9999, (), None, f"TEST {t:%H%M}"))
            t += timedelta(minutes=every)
        return out
    return fetch


def test_calme_donnees_completes_aucune():
    d = decide("t", flight(), RULES, strikes=COVERED, fetch=fake_fetch())
    assert d.status == AUCUNE and d.action == CONTINUER
    assert d.evidence == []


def test_tempete_au_depart_ec_probable_avec_preuves():
    # Rafales à 60 kt de T0-1h à T0+3h : épisode sévère qui couvre le retard.
    d = decide("t", flight(240), RULES, strikes=COVERED,
               fetch=fake_fetch("AAAA", bad_hours=(-1, 0, 1, 2, 3)))
    assert d.status == EC_PROBABLE and d.ec_type == "METEO"
    assert d.fully_explained and d.action == MISE_EN_ATTENTE
    assert d.evidence and all(e["airport"] == "AAAA" for e in d.evidence)
    assert d.rules_version == RULES["version"]


def test_ce_partielle_va_au_juriste():
    # Tempête courte, retard de 10 h : la CE n'explique pas tout le retard.
    d = decide("t", flight(600), RULES, strikes=COVERED, fetch=fake_fetch("AAAA", bad_hours=(0,)))
    assert d.status == EC_PROBABLE
    assert not d.fully_explained
    assert d.remaining_delay_minutes >= 180
    assert d.action == RELECTURE_JURISTE


def test_signal_court_et_modere_incertain():
    # Une seule heure de rafales modérées (40 kt) : ni CE, ni AUCUNE.
    d = decide("t", flight(), RULES, strikes=COVERED, fetch=fake_fetch("AAAA", bad_hours=(0,), gust=40))
    assert d.status == INCERTAIN and d.action == RELECTURE_JURISTE


def test_trou_dans_les_donnees_incertain():
    # Pas de relevé pendant 2 heures : on ne peut pas conclure AUCUNE.
    d = decide("t", flight(), RULES, strikes=COVERED, fetch=fake_fetch(skip_hours=(0, 1)))
    assert d.status == INCERTAIN


def test_panne_de_la_source_incertain():
    def broken(airport, start, end):
        raise ConnectionError("IEM indisponible")
    d = decide("t", flight(), RULES, strikes=COVERED, fetch=broken)
    assert d.status == INCERTAIN
    assert any("IEM indisponible" in r for r in d.reasons)


def test_vol_apres_la_reforme_incertain():
    f = Flight("TEST", "AAAA", "BBBB",
               datetime(2027, 11, 1, 9, tzinfo=timezone.utc),
               datetime(2027, 11, 1, 11, tzinfo=timezone.utc),
               datetime(2027, 11, 1, 13, tzinfo=timezone.utc),
               datetime(2027, 11, 1, 15, tzinfo=timezone.utc))
    d = decide("t", f, RULES, strikes=COVERED, fetch=fake_fetch())
    assert d.status == INCERTAIN and d.legal_regime == "UE_2026_2202"

def test_resume_aeroport_donne_l_episode():
    d = decide("t", flight(240), RULES, strikes=COVERED,
               fetch=fake_fetch("AAAA", bad_hours=(0, 1)))
    dep = next(a for a in d.airports if a["airport"] == "AAAA")
    arr = next(a for a in d.airports if a["airport"] == "BBBB")
    assert dep["episode"] and dep["episode"][0] < dep["episode"][1]
    assert arr["episode"] is None
