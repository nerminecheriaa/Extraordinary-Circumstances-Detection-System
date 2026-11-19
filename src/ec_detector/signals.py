"""Signaux météo : chaque relevé METAR est comparé aux seuils de config/rules.yaml.

Ce module ne décide rien. Il dit seulement, pour un relevé :
quelles règles sont déclenchées, avec quelle sévérité, et sur quelle valeur.
"""

from __future__ import annotations

from dataclasses import dataclass

from ec_detector.models import MetarObs

MODERATE = "moderate"
SEVERE = "severe"


@dataclass(frozen=True)
class Signal:
    rule_id: str        # ex. "wind.severe_gust_kt"
    severity: str       # MODERATE ou SEVERE
    value: str          # valeur observée, ex. "75 kt"
    threshold: str      # seuil appliqué, ex. ">= 50 kt"


def _intensity(code: str) -> str:
    if code.startswith("+"):
        return "+"
    if code.startswith("-"):
        return "-"
    return ""


def _phenomena_signals(obs: MetarObs, rules: list[dict]) -> list[Signal]:
    signals = []
    for code in obs.wx_codes:
        for rule in rules:
            if rule["contains"] not in code:
                continue
            if "intensity" in rule and rule["intensity"] != _intensity(code):
                continue
            signals.append(Signal(
                rule_id=f"phenomena.{rule['contains']}",
                severity=rule["severity"],
                value=code,
                threshold=f"contient {rule['contains']}"
                          + (f", intensité '{rule['intensity']}'" if "intensity" in rule else ""),
            ))
            break  # la première règle qui correspond l'emporte
    return signals


def evaluate(obs: MetarObs, rules: dict) -> list[Signal]:
    """Tous les signaux déclenchés par un relevé."""
    cfg = rules["signals"]
    signals: list[Signal] = []

    # Vent
    wind = cfg["wind"]
    if obs.gust_kt is not None and obs.gust_kt >= wind["severe_gust_kt"]:
        signals.append(Signal("wind.severe_gust_kt", SEVERE,
                              f"{obs.gust_kt:.0f} kt", f">= {wind['severe_gust_kt']} kt"))
    elif obs.gust_kt is not None and obs.gust_kt >= wind["moderate_gust_kt"]:
        signals.append(Signal("wind.moderate_gust_kt", MODERATE,
                              f"{obs.gust_kt:.0f} kt", f">= {wind['moderate_gust_kt']} kt"))
    elif obs.wind_kt is not None and obs.wind_kt >= wind["moderate_mean_kt"]:
        signals.append(Signal("wind.moderate_mean_kt", MODERATE,
                              f"{obs.wind_kt:.0f} kt", f">= {wind['moderate_mean_kt']} kt"))

    # Visibilité
    vis = cfg["visibility"]
    if obs.visibility_m is not None and obs.visibility_m < vis["severe_below_m"]:
        signals.append(Signal("visibility.severe_below_m", SEVERE,
                              f"{obs.visibility_m:.0f} m", f"< {vis['severe_below_m']} m"))
    elif obs.visibility_m is not None and obs.visibility_m < vis["moderate_below_m"]:
        signals.append(Signal("visibility.moderate_below_m", MODERATE,
                              f"{obs.visibility_m:.0f} m", f"< {vis['moderate_below_m']} m"))

    # Plafond
    ceil = cfg["ceiling"]
    if obs.ceiling_ft is not None and obs.ceiling_ft < ceil["moderate_below_ft"]:
        signals.append(Signal("ceiling.moderate_below_ft", MODERATE,
                              f"{obs.ceiling_ft:.0f} ft", f"< {ceil['moderate_below_ft']} ft"))

    # Phénomènes
    signals += _phenomena_signals(obs, cfg["phenomena"])
    return signals


def max_severity(signals: list[Signal]) -> str | None:
    if any(s.severity == SEVERE for s in signals):
        return SEVERE
    if signals:
        return MODERATE
    return None