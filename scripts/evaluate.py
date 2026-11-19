"""Évalue le module sur tous les dossiers annotés de cases/.

    python scripts/evaluate.py                  # tableau, matrice, indicateurs
    python scripts/evaluate.py --json out.json  # + résultat détaillé en JSON

À lancer depuis la racine du repo (chemins relatifs, comme la CLI).
Télécharge les METAR manquants (IEM) puis utilise le cache data/cache/.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from ec_detector.cli import CASES_DIR, run_case
from ec_detector.engine import DEFAULT_RULES_PATH, load_rules
from ec_detector.evaluation import render, row_from, score
from ec_detector.strikes import DEFAULT_STRIKES_PATH, load_strikes


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Évaluation sur les dossiers annotés.")
    parser.add_argument("--cases", default=str(CASES_DIR))
    parser.add_argument("--rules", default=str(DEFAULT_RULES_PATH))
    parser.add_argument("--strikes", default=str(DEFAULT_STRIKES_PATH))
    parser.add_argument("--json", help="écrit le détail (lignes, indicateurs, décisions) en JSON")
    args = parser.parse_args(argv)

    rules = load_rules(Path(args.rules))
    strikes = load_strikes(Path(args.strikes))
    rows, decisions = [], []
    for path in sorted(Path(args.cases).glob("*.yaml")):
        case, decision = run_case(path, rules, strikes)
        rows.append(row_from(case, decision))
        decisions.append(decision.to_dict())

    s = score(rows)
    versions = f"Règles {rules['version']}, calendrier des grèves {strikes.version}"
    print(render(rows, s, versions))

    if args.json:
        Path(args.json).write_text(json.dumps({
            "rules_version": rules["version"],
            "strike_calendar_version": strikes.version,
            "rows": [asdict(r) | {"outcome": r.outcome} for r in rows],
            "score": s,
            "decisions": decisions,
        }, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
