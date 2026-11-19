"""Petite API HTTP + interface de démonstration.

    uvicorn ec_detector.api:app --port 8000      # depuis la racine du repo
    → http://127.0.0.1:8000

Le serveur ne décide rien lui-même : il appelle `decide` et renvoie
`Decision.to_dict()`, le même JSON que la CLI. L'interface (static/) ne fait
qu'afficher ce JSON : aucun seuil, aucune règle côté navigateur.

Endpoints :
    GET  /api/meta        versions, couverture du calendrier, seuil légal
    GET  /api/cases       dossiers de démonstration (cases/) et leurs décisions
    POST /api/decide      un dossier → une décision
    POST /api/decide/batch plusieurs dossiers → plusieurs décisions
    GET  /api/evaluation  indicateurs sur les dossiers annotés
    POST /api/note        un dossier → sa décision + la note pour le juriste (LLM vérifié, D14)

La note est calculée sur une décision recalculée ICI, jamais sur une décision
envoyée par le navigateur : le LLM ne voit que ce que le moteur a produit.
"""

from __future__ import annotations

import threading
from dataclasses import asdict
from pathlib import Path

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ec_detector.engine import Fetcher, decide, load_rules
from ec_detector.evaluation import row_from, score
from ec_detector.models import Flight
from ec_detector.note import LlmClient, NoteStore, client_from_env, load_dotenv, note_for
from ec_detector.strikes import StrikeCalendar, load_strikes
from ec_detector.weather import get_observations

ROOT = Path(__file__).resolve().parents[2]   # racine du repo (installation éditable)
STATIC_DIR = Path(__file__).resolve().parent / "static"
MAX_BATCH = 100
FROM_ENV = object()   # par défaut, le client LLM est lu dans l'environnement (ou .env)
NOTES_DIR = ROOT / "data" / "cache" / "notes"   # ignoré par git, comme le cache METAR


class FlightIn(BaseModel):
    number: str = Field(examples=["TEST003"])
    departure: str = Field(examples=["LFPG"], description="code OACI")
    arrival: str = Field(examples=["LFMN"], description="code OACI")
    scheduled_departure: str = Field(examples=["2025-07-03T07:00:00Z"],
                                     description="ISO 8601 avec fuseau (UTC conseillé)")
    scheduled_arrival: str
    actual_departure: str
    actual_arrival: str


class CaseIn(BaseModel):
    case_id: str = Field(examples=["dossier-123"])
    flight: FlightIn


class BatchIn(BaseModel):
    cases: list[CaseIn] = Field(max_length=MAX_BATCH)


def _require(path: Path) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{path} introuvable : lancer le serveur depuis la racine du repo.")
    return path


def create_app(rules: dict | None = None, strikes: StrikeCalendar | None = None,
               fetch: Fetcher = get_observations, cases_dir: Path | None = None,
               llm: LlmClient | None = FROM_ENV, notes_dir: Path | None = None) -> FastAPI:
    """Fabrique de l'application. Les tests injectent règles, calendrier, `fetch` et `llm`.

    `notes_dir` : dossier où garder les notes (sinon en mémoire seulement).
    """
    rules = rules or load_rules(_require(ROOT / "config" / "rules.yaml"))
    strikes = strikes or load_strikes(_require(ROOT / "data" / "strikes.yaml"))
    cases_dir = cases_dir or ROOT / "cases"
    if llm is FROM_ENV:
        load_dotenv(ROOT / ".env")   # .env est ignoré par git : la clé ne part jamais sur GitHub
        llm = client_from_env()
    llm_model = getattr(llm, "model", None) if llm else None
    # Une note par décision et par modèle : on n'appelle pas le LLM deux fois (quota gratuit).
    notes = NoteStore(notes_dir)

    app = FastAPI(title="ec-detector", version=rules["version"],
                  description="Détection de circonstances extraordinaires (CE 261/2004).")
    lock = threading.Lock()
    cache: dict[str, list] = {}

    def run(case_id: str, flight: dict) -> dict:
        try:
            f = Flight.from_dict(flight)
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=f"Dossier {case_id} invalide : {exc}")
        return decide(case_id, f, rules, fetch=fetch, strikes=strikes).to_dict()

    def demo_cases() -> list[dict]:
        # Calculés une seule fois, sous verrou : pas de téléchargements concurrents.
        with lock:
            if "cases" not in cache:
                out = []
                for path in sorted(Path(cases_dir).glob("*.yaml")):
                    case = yaml.safe_load(path.read_text(encoding="utf-8"))
                    out.append({"case": case,
                                "decision": run(case["case_id"], case["flight"])})
                cache["cases"] = out
            return cache["cases"]

    @app.get("/api/meta")
    def meta() -> dict:
        return {
            "rules_version": rules["version"],
            "strike_calendar_version": strikes.version,
            "compensation_threshold_minutes": rules["legal"]["compensation_threshold_minutes"],
            "note_llm": llm_model if llm else None,
            "reform_application_date": rules["legal"]["reform_application_date"],
            "strike_coverage": [{"zone": c.zone, "from": c.start.isoformat(),
                                 "to": c.end.isoformat()} for c in strikes.coverage],
        }

    @app.get("/api/cases")
    def cases() -> list[dict]:
        # `expected` (l'étiquette d'évaluation) n'est pas exposé ici : voir /api/evaluation.
        return [{
            "case_id": c["case"]["case_id"],
            "description": (c["case"].get("description") or "").strip(),
            "sources": c["case"].get("sources") or [],
            "decision": c["decision"],
        } for c in demo_cases()]

    @app.post("/api/decide")
    def decide_one(body: CaseIn) -> dict:
        return run(body.case_id, body.flight.model_dump())

    @app.post("/api/decide/batch")
    def decide_batch(body: BatchIn) -> list[dict]:
        return [run(c.case_id, c.flight.model_dump()) for c in body.cases]

    @app.post("/api/note")
    def note(body: CaseIn) -> dict:
        dec = run(body.case_id, body.flight.model_dump())
        return {"decision": dec, "note": note_for(dec, llm, llm_model, notes)}

    @app.get("/api/evaluation")
    def evaluation() -> dict:
        class _D:  # adaptateur : row_from attend un objet Decision
            def __init__(self, d): self.__dict__.update(d)
        rows = [row_from(c["case"], _D(c["decision"])) for c in demo_cases()]
        return {"rows": [asdict(r) | {"outcome": r.outcome} for r in rows],
                "score": score(rows),
                "rules_version": rules["version"],
                "strike_calendar_version": strikes.version}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def __getattr__(name: str):
    # `uvicorn ec_detector.api:app` : l'application n'est créée qu'à la demande,
    # pour que l'import du module (tests) ne lise aucun fichier.
    if name == "app":
        return create_app(notes_dir=NOTES_DIR)
    raise AttributeError(name)
