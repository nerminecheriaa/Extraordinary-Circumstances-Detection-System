"""Relevés METAR historiques : téléchargement, cache et lecture.

Source : archive ASOS/METAR de l'Iowa Environmental Mesonet (IEM).
Un fichier de cache par aéroport et par jour (UTC) : chaque journée
n'est téléchargée qu'une seule fois.
"""

from __future__ import annotations

import argparse
import csv
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import time
import requests

from ec_detector.models import MetarObs

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"

# Colonnes demandées à l'IEM (déjà décodées par l'IEM) + le METAR brut.
FIELDS = [
    "sknt", "gust", "vsby", "wxcodes",
    "skyc1", "skyc2", "skyc3", "skyc4",
    "skyl1", "skyl2", "skyl3", "skyl4",
    "metar",
]

DEFAULT_CACHE_DIR = Path("data/cache/metar")
MILES_TO_M = 1609.344
CEILING_COVERS = {"BKN", "OVC", "VV"}
# Politesse envers l'IEM : pause entre deux requêtes, réessais si la source sature.
MIN_INTERVAL_S = 1.0
MAX_RETRIES = 4
RETRY_STATUSES = {429, 500, 502, 503, 504}
_last_request_at = 0.0

# ---------- Téléchargement et cache ----------

def build_params(station: str, day: date) -> list[tuple[str, str]]:
    """Paramètres de la requête IEM pour une journée UTC complète."""
    end = day + timedelta(days=1)
    params = [("station", station)]
    params += [("data", f) for f in FIELDS]
    params += [
        ("year1", str(day.year)), ("month1", str(day.month)), ("day1", str(day.day)),
        ("year2", str(end.year)), ("month2", str(end.month)), ("day2", str(end.day)),
        ("tz", "Etc/UTC"),
        ("format", "onlycomma"),
        ("latlon", "no"),
        ("elev", "no"),
        ("missing", "empty"),
        ("trace", "empty"),
        ("direct", "no"),
        ("report_type", "3"),  # relevés de routine
        ("report_type", "4"),  # relevés spéciaux (SPECI)
    ]
    return params

def _polite_get(http, params):
    """GET avec pause minimale entre requêtes et réessais en cas de saturation."""
    global _last_request_at
    for attempt in range(MAX_RETRIES):
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()

        resp = http.get(IEM_URL, params=params, timeout=60)
        if resp.status_code not in RETRY_STATUSES:
            resp.raise_for_status()
            return resp

        # Saturation : on attend (Retry-After si fourni, sinon 5 s, 10 s, 20 s...).
        retry_after = resp.headers.get("Retry-After", "")
        delay = int(retry_after) if retry_after.isdigit() else 5 * 2 ** attempt
        time.sleep(delay)

    resp.raise_for_status()  # après le dernier essai : l'erreur remonte
    return resp

def fetch_day_csv(station: str, day: date,
                  cache_dir: Path = DEFAULT_CACHE_DIR, session=None) -> str:
    """CSV IEM d'une journée. Lit le cache s'il existe, sinon télécharge."""
    path = Path(cache_dir) / station / f"{day.isoformat()}.csv"
    if path.exists():
        return path.read_text(encoding="utf-8")

    http = session or requests
    resp = _polite_get(http, build_params(station, day))
    text = resp.text

    # On ne met jamais en cache une réponse qui n'est pas un CSV valide.
    if not text.startswith("station,"):
        raise ValueError(
            f"Réponse inattendue de l'IEM pour {station} le {day}: {text[:200]!r}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


# ---------- Lecture ----------

def _to_float(value: str | None) -> float | None:
    if value is None or value.strip() == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _ceiling_ft(row: dict) -> float | None:
    """Plafond = plus basse couche couvrante (BKN, OVC) ou ciel invisible (VV)."""
    heights = []
    for i in range(1, 5):
        cover = (row.get(f"skyc{i}") or "").strip()
        height = _to_float(row.get(f"skyl{i}"))
        if cover in CEILING_COVERS and height is not None:
            heights.append(height)
    return min(heights) if heights else None


def parse_csv(text: str) -> list[MetarObs]:
    """Transforme le CSV de l'IEM en relevés triés par heure."""
    observations = []
    for row in csv.DictReader(io.StringIO(text)):
        vsby_miles = _to_float(row.get("vsby"))
        observations.append(MetarObs(
            station=row["station"].strip(),
            observed_at=datetime.strptime(row["valid"].strip(), "%Y-%m-%d %H:%M")
                                .replace(tzinfo=timezone.utc),
            wind_kt=_to_float(row.get("sknt")),
            gust_kt=_to_float(row.get("gust")),
            visibility_m=None if vsby_miles is None else round(vsby_miles * MILES_TO_M),
            wx_codes=tuple((row.get("wxcodes") or "").split()),
            ceiling_ft=_ceiling_ft(row),
            raw=(row.get("metar") or "").strip(),
        ))
    return sorted(observations, key=lambda o: o.observed_at)


# ---------- Point d'entrée principal ----------

def get_observations(station: str, start: datetime, end: datetime,
                     cache_dir: Path = DEFAULT_CACHE_DIR, session=None) -> list[MetarObs]:
    """Relevés d'un aéroport entre `start` et `end` (inclus), en UTC."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start et end doivent avoir un fuseau horaire (UTC).")
    if end < start:
        raise ValueError("end doit être après start.")

    station = station.upper()
    start, end = start.astimezone(timezone.utc), end.astimezone(timezone.utc)

    observations: dict[tuple, MetarObs] = {}
    day = start.date()
    while day <= end.date():
        for obs in parse_csv(fetch_day_csv(station, day, cache_dir, session)):
            observations[(obs.observed_at, obs.raw)] = obs  # supprime les doublons
        day += timedelta(days=1)

    return sorted(
        (o for o in observations.values() if start <= o.observed_at <= end),
        key=lambda o: o.observed_at,
    )


def main(argv: list[str] | None = None) -> None:
    """Outil de développement : télécharge et affiche une journée."""
    parser = argparse.ArgumentParser(description="Affiche les METAR d'une journée (UTC).")
    parser.add_argument("station", help="code OACI, ex. LFPG")
    parser.add_argument("day", help="date AAAA-MM-JJ")
    args = parser.parse_args(argv)

    day = date.fromisoformat(args.day)
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    obs = get_observations(args.station, start, start + timedelta(hours=23, minutes=59))

    print(f"{len(obs)} relevés pour {args.station.upper()} le {day}")
    for o in obs:
        print(f"{o.observed_at:%H:%M}Z  vent={o.wind_kt} rafales={o.gust_kt} "
              f"visi={o.visibility_m}m plafond={o.ceiling_ft}ft wx={' '.join(o.wx_codes) or 'aucun'}")
        print(f"        {o.raw}")


if __name__ == "__main__":
    main()