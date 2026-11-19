"""Grèves du contrôle aérien : calendrier sourcé à la main (data/strikes.yaml).

Ce module ne décide rien. Pour un aéroport et une fenêtre de temps, il dit :
- si le calendrier couvre cette zone et cette période (sinon, on ne sait pas) ;
- quelles grèves touchent la fenêtre, et comment :
    * CONFIRMED_AIRPORT : grève confirmée, aéroport cité par une source ;
    * ZONE_ONLY         : grève confirmée dans la zone, aéroport non confirmé ;
    * ANNOUNCED         : préavis seulement, grève non confirmée.

Principe (voir docs/decisions.md, D12) : l'absence de grève dans le calendrier
ne vaut « pas de grève » que si la zone et la période sont déclarées couvertes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from ec_detector.models import parse_utc

DEFAULT_STRIKES_PATH = Path("data/strikes.yaml")

CONFIRMED = "confirmed"
ANNOUNCED = "announced"
CANCELLED = "cancelled"
STATUSES = {CONFIRMED, ANNOUNCED, CANCELLED}

# Types de correspondance entre une grève et un aéroport.
CONFIRMED_AIRPORT = "CONFIRMED_AIRPORT"
ZONE_ONLY = "ZONE_ONLY"


@dataclass(frozen=True)
class Coverage:
    """Zone et période pour lesquelles le calendrier a été vérifié."""

    zone: str                  # préfixe OACI, ex. "LF" pour la France métropolitaine
    start: datetime
    end: datetime
    checked_by: str
    note: str = ""

    def covers(self, airport: str, start: datetime, end: datetime) -> bool:
        return airport.startswith(self.zone) and self.start <= start and end <= self.end


@dataclass(frozen=True)
class Strike:
    id: str
    status: str                       # confirmed, announced ou cancelled
    zone: str                         # préfixe OACI de la zone touchée
    confirmed_airports: tuple[str, ...]
    start: datetime
    end: datetime
    timing: str                       # "day" : journées entières, horaires précis non sourcés
    unions: tuple[str, ...]
    sources: tuple[str, ...]
    note: str = ""

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and start < self.end

    def to_dict(self) -> dict:
        return {
            "id": self.id, "status": self.status, "zone": self.zone,
            "confirmed_airports": list(self.confirmed_airports),
            "period": [self.start.isoformat(), self.end.isoformat()],
            "timing": self.timing, "unions": list(self.unions),
            "sources": list(self.sources),
        }


@dataclass(frozen=True)
class StrikeMatch:
    strike: Strike
    kind: str                 # CONFIRMED_AIRPORT, ZONE_ONLY ou ANNOUNCED


@dataclass
class StrikeCalendar:
    version: str
    coverage: list[Coverage] = field(default_factory=list)
    strikes: list[Strike] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> StrikeCalendar:
        if not isinstance(data, dict) or "version" not in data:
            raise ValueError("calendrier des grèves vide ou sans version")
        coverage = [
            Coverage(zone=c["zone"], start=parse_utc(c["from"]), end=parse_utc(c["to"]),
                     checked_by=c["checked_by"], note=c.get("note", ""))
            for c in data.get("coverage") or []
        ]
        strikes = []
        for s in data.get("strikes") or []:
            if s["status"] not in STATUSES:
                raise ValueError(f"grève {s['id']} : statut inconnu {s['status']!r}")
            strike = Strike(
                id=s["id"], status=s["status"], zone=s["zone"],
                confirmed_airports=tuple(a.upper() for a in s.get("confirmed_airports") or []),
                start=parse_utc(s["start"]), end=parse_utc(s["end"]),
                timing=s.get("timing", "day"),
                unions=tuple(s.get("unions") or []),
                sources=tuple(s.get("sources") or []),
                note=s.get("note", ""),
            )
            if strike.end <= strike.start:
                raise ValueError(f"grève {strike.id} : fin avant le début")
            if strike.status != CANCELLED and not strike.sources:
                raise ValueError(f"grève {strike.id} : aucune source")
            strikes.append(strike)
        return cls(version=str(data["version"]), coverage=coverage, strikes=strikes)

    def is_covered(self, airport: str, start: datetime, end: datetime) -> bool:
        return any(c.covers(airport, start, end) for c in self.coverage)

    def matches(self, airport: str, start: datetime, end: datetime) -> list[StrikeMatch]:
        out = []
        for s in self.strikes:
            if s.status == CANCELLED or not s.overlaps(start, end):
                continue
            if not airport.startswith(s.zone) and airport not in s.confirmed_airports:
                continue
            if s.status == ANNOUNCED:
                out.append(StrikeMatch(s, ANNOUNCED))
            elif airport in s.confirmed_airports:
                out.append(StrikeMatch(s, CONFIRMED_AIRPORT))
            else:
                out.append(StrikeMatch(s, ZONE_ONLY))
        return out


def load_strikes(path: Path = DEFAULT_STRIKES_PATH) -> StrikeCalendar:
    return StrikeCalendar.from_dict(yaml.safe_load(Path(path).read_text(encoding="utf-8")))
