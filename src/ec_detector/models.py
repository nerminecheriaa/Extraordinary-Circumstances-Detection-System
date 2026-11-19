"""Structures de données du projet."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class MetarObs:
    """Un relevé METAR, déjà converti en unités simples.

    Toutes les heures sont en UTC. `None` signifie : valeur absente du relevé.
    """

    station: str                 # code OACI de l'aéroport, ex. "LFPG"
    observed_at: datetime        # heure du relevé (UTC)
    wind_kt: float | None        # vent moyen, en nœuds
    gust_kt: float | None        # rafales, en nœuds
    visibility_m: float | None   # visibilité, en mètres
    wx_codes: tuple[str, ...]    # phénomènes, ex. ("+SN", "BR")
    ceiling_ft: float | None     # plafond : plus basse couche BKN/OVC/VV, en pieds
    raw: str                     # texte METAR brut, gardé comme preuve


def parse_utc(value: str) -> datetime:
    """Lit une heure ISO 8601 et exige un fuseau horaire. Renvoie de l'UTC."""
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"Heure sans fuseau horaire : {value!r}")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Flight:
    """Le vol d'un dossier : aéroports et horaires (UTC)."""

    number: str
    departure: str               # code OACI
    arrival: str                 # code OACI
    scheduled_departure: datetime
    scheduled_arrival: datetime
    actual_departure: datetime
    actual_arrival: datetime

    @classmethod
    def from_dict(cls, data: dict) -> Flight:
        flight = cls(
            number=str(data["number"]),
            departure=str(data["departure"]).upper(),
            arrival=str(data["arrival"]).upper(),
            scheduled_departure=parse_utc(data["scheduled_departure"]),
            scheduled_arrival=parse_utc(data["scheduled_arrival"]),
            actual_departure=parse_utc(data["actual_departure"]),
            actual_arrival=parse_utc(data["actual_arrival"]),
        )
        flight._check()
        return flight

    def _check(self) -> None:
        if self.scheduled_arrival <= self.scheduled_departure:
            raise ValueError(f"{self.number} : arrivée prévue avant le départ prévu.")
        if self.actual_arrival <= self.actual_departure:
            raise ValueError(f"{self.number} : arrivée réelle avant le départ réel.")

    @property
    def arrival_delay_minutes(self) -> int:
        """Retard à l'arrivée : c'est lui qui compte pour l'indemnisation."""
        return int((self.actual_arrival - self.scheduled_arrival).total_seconds() // 60)