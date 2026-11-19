"""Ligne de commande.

    python -m ec_detector.cli cases/munich_neige_2023-12-02.yaml   # décision JSON complète
    python -m ec_detector.cli --all                                 # résumé de tous les cas
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from ec_detector.engine import DEFAULT_RULES_PATH, decide, load_rules
from ec_detector.models import Flight
from ec_detector.strikes import DEFAULT_STRIKES_PATH, load_strikes

CASES_DIR = Path("cases")


def run_case(path: Path, rules: dict, strikes=None):
    case = yaml.safe_load(path.read_text(encoding="utf-8"))
    decision = decide(case["case_id"], Flight.from_dict(case["flight"]), rules,
                      strikes=strikes)
    return case, decision


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Détection de circonstances extraordinaires.")
    parser.add_argument("case", nargs="?", help="fichier YAML d'un dossier")
    parser.add_argument("--all", action="store_true", help="résumé de tous les cas de cases/")
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH))
    parser.add_argument("--strikes", default=str(DEFAULT_STRIKES_PATH))
    args = parser.parse_args(argv)
    rules = load_rules(Path(args.rules))
    strikes = load_strikes(Path(args.strikes))

    if args.all:
        print(f"Règles version {rules['version']}, calendrier des grèves {strikes.version}")
        print(f"{'cas':32} {'attendu':24} {'obtenu':24} {'action':18} {'expliqué':>9}")
        for path in sorted(CASES_DIR.glob("*.yaml")):
            case, d = run_case(path, rules, strikes)
            exp = case["expected"]
            expected = f"{exp['status']}/{exp.get('ec_type') or '-'}"
            got = f"{d.status}/{d.ec_type or '-'}"
            print(f"{case['case_id']:32} {expected:24} {got:24} {d.action:18} "
                  f"{d.delay_explained_minutes:>4}/{d.delay_total_minutes:<4}")
        return

    if not args.case:
        parser.error("donner un fichier de cas, ou --all")
    _, decision = run_case(Path(args.case), rules, strikes)
    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()