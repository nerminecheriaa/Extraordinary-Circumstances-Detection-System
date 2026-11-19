"""Contrôle qualité des dossiers de test du dossier cases/."""

from pathlib import Path

import pytest
import yaml

from ec_detector.models import Flight

CASES_DIR = Path(__file__).resolve().parent.parent / "cases"
CASE_FILES = sorted(CASES_DIR.glob("*.yaml"))
VALID_STATUSES = {"EC_PROBABLE", "AUCUNE", "INCERTAIN"}


def test_il_y_a_des_cas():
    assert CASE_FILES, "Aucun dossier de test dans cases/"


@pytest.mark.parametrize("path", CASE_FILES, ids=lambda p: p.stem)
def test_cas_valide(path):
    case = yaml.safe_load(path.read_text(encoding="utf-8"))

    # Le nom du fichier et l'identifiant concordent.
    assert case["case_id"] == path.stem

    # Les horaires sont lisibles et cohérents (UTC, arrivée après départ).
    flight = Flight.from_dict(case["flight"])
    assert flight.arrival_delay_minutes >= 0

    # La réponse attendue utilise un statut connu.
    assert case["expected"]["status"] in VALID_STATUSES

    # Un événement présenté comme réel doit être sourcé.
    if case["verification"].get("event_confirmed"):
        assert case["sources"], f"{path.name} : événement confirmé sans source"