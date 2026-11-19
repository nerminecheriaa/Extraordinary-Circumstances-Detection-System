"""Pré-génère les notes pour le juriste des dossiers de cases/ (avant une démonstration).

    python scripts/prepare_notes.py

L'offre gratuite de Mistral limite à 2 requêtes par minute : le script attend
entre deux appels. Les notes sont gardées dans data/cache/notes/ (ignoré par
git) et l'interface les affiche ensuite instantanément. Une note déjà présente
n'est pas régénérée.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ec_detector.api import NOTES_DIR  # noqa: E402
from ec_detector.engine import decide, load_rules  # noqa: E402
from ec_detector.models import Flight  # noqa: E402
from ec_detector.note import LLM, NoteStore, client_from_env, load_dotenv, note_for  # noqa: E402
from ec_detector.strikes import load_strikes  # noqa: E402

PAUSE_SECONDS = 31   # 2 requêtes par minute sur l'offre gratuite


def main() -> int:
    load_dotenv(ROOT / ".env")
    llm = client_from_env()
    if llm is None:
        print("MISTRAL_API_KEY absente (.env) : rien à préparer, l'interface utilisera le modèle fixe.")
        return 1
    rules = load_rules(ROOT / "config" / "rules.yaml")
    strikes = load_strikes(ROOT / "data" / "strikes.yaml")
    store = NoteStore(NOTES_DIR)
    print(f"Modèle {llm.model}, notes dans {NOTES_DIR}")

    failed = 0
    for path in sorted((ROOT / "cases").glob("*.yaml")):
        case = yaml.safe_load(path.read_text(encoding="utf-8"))
        dec = decide(case["case_id"], Flight.from_dict(case["flight"]), rules,
                     strikes=strikes).to_dict()
        note = note_for(dec, llm, llm.model, store)
        if note["from_cache"]:
            print(f"  déjà prête   {case['case_id']}")
            continue
        if note["source"] == LLM:
            print(f"  IA, vérifiée {case['case_id']}")
        else:
            failed += 1
            print(f"  modèle fixe  {case['case_id']} : {note['fallback_reason']}")
            for p in note["llm_problems"]:
                print(f"               - {p}")
        time.sleep(PAUSE_SECONDS)

    print("Terminé." if not failed else
          f"Terminé, {failed} dossier(s) en modèle fixe. Relancer le script pour réessayer "
          "ceux qui ont échoué à cause du quota.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
