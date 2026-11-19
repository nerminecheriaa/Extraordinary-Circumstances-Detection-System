"""Moteur de décision : relevés météo + calendrier des grèves ATC
-> statut, preuves, minutes de retard expliquées.

Principes :
- le code décide, avec des règles explicites et versionnées (config/rules.yaml) ;
- dans le doute, un humain : seul un dossier sans aucun signal, avec des données
  météo complètes et un calendrier des grèves qui couvre les deux aéroports,
  passe en AUCUNE ;
- chaque décision garde ses preuves, la version des règles et la date du calcul.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

import yaml

from ec_detector.models import Flight, MetarObs
from ec_detector.signals import SEVERE, evaluate, max_severity
from ec_detector.strikes import (ANNOUNCED, CONFIRMED_AIRPORT, DEFAULT_STRIKES_PATH,
                                 StrikeCalendar, StrikeMatch, load_strikes)
from ec_detector.weather import get_observations

EC_PROBABLE = "EC_PROBABLE"
AUCUNE = "AUCUNE"
INCERTAIN = "INCERTAIN"

# Action proposée au produit pour chaque issue.
CONTINUER = "CONTINUER"
MISE_EN_ATTENTE = "MISE_EN_ATTENTE"
RELECTURE_JURISTE = "RELECTURE_JURISTE"

DEFAULT_RULES_PATH = Path("config/rules.yaml")

Fetcher = Callable[[str, datetime, datetime], list[MetarObs]]


def load_rules(path: Path = DEFAULT_RULES_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


# ---------- Fenêtres de temps ----------

@dataclass(frozen=True)
class Window:
    airport: str
    role: str              # "départ" ou "arrivée"
    scheduled: datetime
    actual: datetime
    start: datetime
    end: datetime


def build_windows(flight: Flight, rules: dict) -> list[Window]:
    """Une fenêtre par aéroport : de (prévu - marge) à l'heure réelle, plafonnée."""
    w = rules["window"]
    before = timedelta(minutes=w["before_scheduled_minutes"])
    max_after = timedelta(minutes=w["max_after_scheduled_minutes"])

    windows = []
    for airport, role, scheduled, actual in [
        (flight.departure, "départ", flight.scheduled_departure, flight.actual_departure),
        (flight.arrival, "arrivée", flight.scheduled_arrival, flight.actual_arrival),
    ]:
        end = max(scheduled, min(actual, scheduled + max_after))
        windows.append(Window(airport, role, scheduled, actual, scheduled - before, end))
    return windows


# ---------- Analyse d'un aéroport ----------

@dataclass
class AirportAnalysis:
    airport: str
    role: str
    window_start: datetime
    window_end: datetime
    n_obs: int = 0
    data_complete: bool = False
    max_gap_minutes: int = 0
    severe_minutes: int = 0
    signal_minutes: int = 0          # minutes avec au moins un signal (modéré ou sévère)
    is_ec: bool = False
    episode_start: datetime | None = None
    episode_end: datetime | None = None
    error: str | None = None
    evidence: list[dict] = field(default_factory=list)


def _durations(obs: list[MetarObs], end: datetime, rules: dict) -> list[int]:
    """Minutes représentées par chaque relevé : jusqu'au suivant, 60 min au plus."""
    default = rules["window"]["default_obs_minutes"]
    durations = []
    for i, o in enumerate(obs):
        if i + 1 < len(obs):
            durations.append(min(_minutes(obs[i + 1].observed_at - o.observed_at), 60))
        else:
            durations.append(max(0, min(_minutes(end - o.observed_at), default)))
    return durations


def _max_gap(obs: list[MetarObs], start: datetime, end: datetime) -> int:
    points = [start] + [o.observed_at for o in obs] + [end]
    return max(_minutes(b - a) for a, b in zip(points, points[1:]))


def analyse_airport(window: Window, obs: list[MetarObs], rules: dict) -> AirportAnalysis:
    a = AirportAnalysis(window.airport, window.role, window.start, window.end)
    a.n_obs = len(obs)
    a.max_gap_minutes = _max_gap(obs, window.start, window.end)
    a.data_complete = bool(obs) and a.max_gap_minutes <= rules["window"]["max_gap_minutes"]

    for o, minutes in zip(obs, _durations(obs, window.end, rules)):
        signals = evaluate(o, rules)
        severity = max_severity(signals)
        if severity is None:
            continue
        a.signal_minutes += minutes
        if severity == SEVERE:
            a.severe_minutes += minutes
        a.episode_start = a.episode_start or o.observed_at
        a.episode_end = o.observed_at + timedelta(minutes=minutes)
        a.evidence.append({
            "airport": window.airport,
            "role": window.role,
            "observed_at": o.observed_at.isoformat(),
            "raw": o.raw,
            "signals": [asdict(s) for s in signals],
        })

    ep = rules["episode"]
    a.is_ec = (a.severe_minutes >= ep["min_severe_minutes"]
               or a.signal_minutes >= ep["min_moderate_minutes"])
    return a


# ---------- Minutes de retard expliquées ----------

def explained_minutes(a: AirportAnalysis, window: Window, rules: dict) -> int:
    """Approximation : chevauchement entre l'épisode (+ remise en état)
    et la période de retard [heure prévue, heure réelle] à cet aéroport."""
    if not a.is_ec or a.episode_start is None:
        return 0
    recovery = timedelta(minutes=rules["episode"]["recovery_minutes"])
    start = max(a.episode_start, window.scheduled)
    end = min(a.episode_end + recovery, window.actual)
    return max(0, _minutes(end - start))


def legal_regime(flight: Flight, rules: dict) -> str:
    reform = date.fromisoformat(rules["legal"]["reform_application_date"])
    return "UE_2026_2202" if flight.scheduled_departure.date() >= reform else "CE_261_2004"


# ---------- Grèves du contrôle aérien ----------

@dataclass
class StrikeAnalysis:
    airport: str
    role: str
    covered: bool = False
    matches: list[StrikeMatch] = field(default_factory=list)
    explained: int = 0                 # minutes imputables à une grève confirmée

    @property
    def confirmed(self) -> list[StrikeMatch]:
        return [m for m in self.matches if m.kind == CONFIRMED_AIRPORT]

    @property
    def doubtful(self) -> list[StrikeMatch]:
        return [m for m in self.matches if m.kind != CONFIRMED_AIRPORT]


def analyse_strikes(window: Window, calendar: StrikeCalendar) -> StrikeAnalysis:
    a = StrikeAnalysis(window.airport, window.role)
    a.covered = calendar.is_covered(window.airport, window.start, window.end)
    a.matches = calendar.matches(window.airport, window.start, window.end)
    # Approximation à la journée (timing "day") : chevauchement entre la période
    # de grève et la période de retard [heure prévue, heure réelle].
    for m in a.confirmed:
        start = max(m.strike.start, window.scheduled)
        end = min(m.strike.end, window.actual)
        a.explained = max(a.explained, _minutes(end - start))
    return a


def _strike_evidence(a: StrikeAnalysis) -> list[dict]:
    return [{
        "source": "CALENDRIER_GREVES",
        "airport": a.airport,
        "role": a.role,
        "rule_id": f"strike.{m.kind.lower()}",
        "strike": m.strike.to_dict(),
    } for m in a.matches]


# ---------- Décision ----------

@dataclass
class Decision:
    case_id: str
    status: str
    action: str
    ec_type: str | None              # type principal (celui qui explique le plus de minutes)
    ec_types: list[str]              # tous les types de CE retenus
    confidence: float
    delay_total_minutes: int
    delay_explained_minutes: int
    remaining_delay_minutes: int
    fully_explained: bool
    reasons: list[str]
    explanation: str
    evidence: list[dict]
    airports: list[dict]
    strike_check: dict
    flight: dict
    legal_regime: str
    rules_version: str
    strike_calendar_version: str | None
    computed_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _airport_summary(a: AirportAnalysis) -> dict:
    return {
        "airport": a.airport, "role": a.role,
        "window": [a.window_start.isoformat(), a.window_end.isoformat()],
        "n_obs": a.n_obs, "data_complete": a.data_complete,
        "max_gap_minutes": a.max_gap_minutes,
        "severe_minutes": a.severe_minutes, "signal_minutes": a.signal_minutes,
        "is_ec": a.is_ec, "error": a.error,
        "episode": ([a.episode_start.isoformat(), a.episode_end.isoformat()]
                    if a.episode_start and a.episode_end else None),
    }


def _strike_summary(analyses: list[StrikeAnalysis], error: str | None) -> dict:
    return {
        "error": error,
        "airports": [{
            "airport": a.airport, "role": a.role, "covered": a.covered,
            "matches": [{"strike_id": m.strike.id, "kind": m.kind} for m in a.matches],
        } for a in analyses],
    }


def _flight_dict(f: Flight) -> dict:
    return {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(f).items()}


def _load_default_strikes() -> StrikeCalendar:
    return load_strikes(DEFAULT_STRIKES_PATH)


def decide(case_id: str, flight: Flight, rules: dict,
           fetch: Fetcher = get_observations, now: datetime | None = None,
           strikes: StrikeCalendar | None = None) -> Decision:
    """`strikes` : calendrier des grèves. Absent → lu dans data/strikes.yaml.
    Un calendrier illisible ne bloque pas le calcul, mais interdit AUCUNE."""
    now = now or datetime.now(timezone.utc)
    threshold = rules["legal"]["compensation_threshold_minutes"]
    conf = rules["confidence"]
    delay = flight.arrival_delay_minutes
    regime = legal_regime(flight, rules)
    windows = build_windows(flight, rules)

    # --- Météo
    analyses = []
    for w in windows:
        try:
            obs = fetch(w.airport, w.start, w.end)
            analyses.append(analyse_airport(w, obs, rules))
        except Exception as exc:  # panne réseau, station inconnue... → jamais AUCUNE
            a = AirportAnalysis(w.airport, w.role, w.start, w.end, error=str(exc))
            analyses.append(a)

    # --- Grèves ATC
    strike_error = None
    if strikes is None:
        try:
            strikes = _load_default_strikes()
        except Exception as exc:  # fichier absent, vide ou invalide → jamais AUCUNE
            strike_error = f"calendrier des grèves illisible : {exc}"
    strike_analyses = ([analyse_strikes(w, strikes) for w in windows]
                       if strikes is not None else [])

    # --- CE retenues, par type : (minutes expliquées, confiance, raisons)
    found: dict[str, tuple[int, float, list[str]]] = {}

    ec_airports = [a for a in analyses if a.is_ec]
    if ec_airports:
        severe = any(a.severe_minutes >= rules["episode"]["min_severe_minutes"]
                     for a in ec_airports)
        minutes = max(explained_minutes(a, w, rules) for a, w in zip(analyses, windows))
        found["METEO"] = (minutes, conf["ec_severe"] if severe else conf["ec_persistent"], [
            f"Météo grave à {a.airport} ({a.role}) : {a.severe_minutes} min sévères, "
            f"{a.signal_minutes} min avec signal, de {a.episode_start:%d/%m %H:%M}Z "
            f"à {a.episode_end:%d/%m %H:%M}Z."
            for a in ec_airports
        ])

    strike_ec = [a for a in strike_analyses if a.confirmed]
    if strike_ec:
        found["GREVE_ATC"] = (max(a.explained for a in strike_ec), conf["ec_strike_confirmed"], [
            f"Grève du contrôle aérien {m.strike.id}"
            + (f" ({', '.join(m.strike.unions)})" if m.strike.unions else "")
            + " "
            f"confirmée à {a.airport} ({a.role}), du {m.strike.start:%d/%m %H:%M}Z "
            f"au {m.strike.end:%d/%m %H:%M}Z. Imputation à la journée : horaires "
            "précis de la grève non sourcés."
            for a in strike_ec for m in a.confirmed
        ])

    # --- Raisons de doute (empêchent AUCUNE)
    doubts: list[str] = []
    for a in analyses:
        if not a.data_complete:
            detail = a.error or f"{a.n_obs} relevés, trou max {a.max_gap_minutes} min"
            doubts.append(f"Données météo incomplètes à {a.airport} ({a.role}) : {detail}.")
        elif a.signal_minutes > 0 and not a.is_ec:
            doubts.append(f"Signaux météo trop faibles ou trop courts à {a.airport} "
                          f"({a.role}) : {a.signal_minutes} min.")
    if strike_error:
        doubts.append(strike_error + ".")
    for a in strike_analyses:
        if not a.covered:
            doubts.append(f"Calendrier des grèves non vérifié pour {a.airport} ({a.role}) "
                          "à cette date : l'absence de grève n'est pas établie.")
        for m in a.doubtful:
            what = ("préavis non confirmé" if m.kind == ANNOUNCED
                    else "grève confirmée dans la zone, aéroport non confirmé par une source")
            doubts.append(f"Grève ATC {m.strike.id} à {a.airport} ({a.role}) : {what}.")

    # --- Statut
    reasons: list[str] = []
    ec_type, ec_types, explained = None, [], 0

    if regime != "CE_261_2004":
        status, confidence = INCERTAIN, conf["uncertain"]
        reasons.append(f"Vol soumis au régime {regime} : règles non implémentées.")
    elif found:
        status = EC_PROBABLE
        ec_types = sorted(found, key=lambda t: -found[t][0])
        ec_type = ec_types[0]
        explained = min(delay, found[ec_type][0])
        confidence = max(c for _, c, _ in found.values())
        for t in ec_types:
            reasons += found[t][2]
    elif doubts:
        status, confidence = INCERTAIN, conf["uncertain"]
        reasons += doubts
    else:
        status, confidence = AUCUNE, conf["none_full_data"]
        reasons.append("Aucun signal météo aux deux aéroports, données complètes.")
        reasons.append(f"Aucune grève ATC aux deux aéroports (calendrier {strikes.version}, "
                       "zone et période couvertes).")

    remaining = delay - explained
    fully_explained = status == EC_PROBABLE and remaining < threshold

    if status == EC_PROBABLE and fully_explained:
        action = MISE_EN_ATTENTE
    elif status == AUCUNE:
        action = CONTINUER
    else:
        action = RELECTURE_JURISTE
    if status == EC_PROBABLE and not fully_explained:
        reasons.append(
            f"La CE n'explique qu'environ {explained} min sur {delay} : il reste "
            f"{remaining} min, au-dessus du seuil de {threshold} min. "
            "Le lien entre la CE et tout le retard est à établir par un juriste."
        )

    explanation = (
        f"Statut {status} (confiance {confidence}). Retard à l'arrivée : {delay} min ; "
        f"minutes imputables estimées : {explained} ; retard restant : {remaining} min. "
        + " ".join(reasons)
    )

    evidence = ([dict(e, source="METAR") for a in analyses for e in a.evidence]
                + [e for a in strike_analyses for e in _strike_evidence(a)])
    return Decision(
        case_id=case_id,
        status=status,
        action=action,
        ec_type=ec_type,
        ec_types=ec_types,
        confidence=confidence,
        delay_total_minutes=delay,
        delay_explained_minutes=explained,
        remaining_delay_minutes=remaining,
        fully_explained=fully_explained,
        reasons=reasons,
        explanation=explanation,
        evidence=evidence,
        airports=[_airport_summary(a) for a in analyses],
        strike_check=_strike_summary(strike_analyses, strike_error),
        flight=_flight_dict(flight),
        legal_regime=regime,
        rules_version=rules["version"],
        strike_calendar_version=strikes.version if strikes is not None else None,
        computed_at=now.isoformat(),
    )
