"""Tests des signaux. Relevés SYNTHÉTIQUES (station TEST), pas des données réelles."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from ec_detector.engine import load_rules
from ec_detector.models import MetarObs
from ec_detector.signals import MODERATE, SEVERE, evaluate, max_severity

RULES = load_rules(Path(__file__).resolve().parent.parent / "config" / "rules.yaml")


def obs(wind=5, gust=None, vis=9999, ceiling=None, wx=()):
    return MetarObs("TEST", datetime(2030, 1, 1, tzinfo=timezone.utc),
                    wind, gust, vis, tuple(wx), ceiling, "TEST SYNTHETIQUE")


def rule_ids(o):
    return {s.rule_id for s in evaluate(o, RULES)}


def test_journee_calme_aucun_signal():
    assert evaluate(obs(), RULES) == []


@pytest.mark.parametrize("gust, expected", [
    (30, None), (35, MODERATE), (49, MODERATE), (50, SEVERE), (75, SEVERE),
])
def test_seuils_rafales(gust, expected):
    assert max_severity(evaluate(obs(gust=gust), RULES)) == expected


def test_plafond_bas():
    assert "ceiling.moderate_below_ft" in rule_ids(obs(ceiling=100))
    assert "ceiling.moderate_below_ft" not in rule_ids(obs(ceiling=200))


@pytest.mark.parametrize("code, expected", [
    ("-SN", None),          # neige faible : pas une météo grave
    ("SN", MODERATE),
    ("+SN", SEVERE),
    ("TSRA", MODERATE),
    ("+TSRA", SEVERE),
    ("FZRA", SEVERE),
    ("-FZDZ", SEVERE),      # verglaçant : sévère même faible
    ("BR", None),
])
def test_phenomenes(code, expected):
    assert max_severity(evaluate(obs(wx=[code]), RULES)) == expected


def test_valeur_absente_ne_declenche_rien():
    o = MetarObs("TEST", datetime(2030, 1, 1, tzinfo=timezone.utc),
                 None, None, None, (), None, "TEST SYNTHETIQUE")
    assert evaluate(o, RULES) == []