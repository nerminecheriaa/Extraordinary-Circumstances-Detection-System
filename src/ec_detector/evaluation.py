"""Évaluation sur les dossiers annotés : fonctions pures, sans réseau.

`expected.status` d'un dossier est l'étiquette de vérité (hypothèse à confirmer
par un juriste). Chaque dossier tombe dans une des trois classes :
- CORRECT : statut obtenu = statut attendu ;
- RENVOYE : le module dit INCERTAIN alors que la vérité est tranchée → un humain
  relit. Ce n'est pas une erreur, c'est un coût (moins d'automatisation) ;
- FAUX    : le module tranche, et se trompe.

Automatisé = action CONTINUER ou MISE_EN_ATTENTE (aucun humain).
Erreur critique = CONTINUER alors qu'une CE est plausible : le dossier part
seul vers un procès fragile.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

STATUSES = ("EC_PROBABLE", "AUCUNE", "INCERTAIN")
AUTOMATED_ACTIONS = {"CONTINUER", "MISE_EN_ATTENTE"}

CORRECT = "CORRECT"
DEFERRED = "RENVOYE"
WRONG = "FAUX"


@dataclass(frozen=True)
class Row:
    case_id: str
    expected_status: str
    expected_type: str | None
    status: str
    ec_type: str | None
    action: str
    explained: int = 0
    delay: int = 0

    @property
    def automated(self) -> bool:
        return self.action in AUTOMATED_ACTIONS

    @property
    def outcome(self) -> str:
        if self.status == self.expected_status:
            return CORRECT
        if self.status == "INCERTAIN":
            return DEFERRED
        return WRONG

    @property
    def type_mismatch(self) -> bool:
        return (self.status == "EC_PROBABLE" == self.expected_status
                and self.ec_type != self.expected_type)

    @property
    def critical(self) -> bool:
        """Continué seul alors que la vérité n'est pas « aucune CE »."""
        return self.action == "CONTINUER" and self.expected_status != "AUCUNE"

    @property
    def good_case_dropped(self) -> bool:
        """Mis en attente seul alors qu'il n'y a pas de CE : argent perdu."""
        return self.action == "MISE_EN_ATTENTE" and self.expected_status != "EC_PROBABLE"


def row_from(case: dict, decision) -> Row:
    exp = case["expected"]
    return Row(case_id=case["case_id"], expected_status=exp["status"],
               expected_type=exp.get("ec_type"), status=decision.status,
               ec_type=decision.ec_type, action=decision.action,
               explained=decision.delay_explained_minutes,
               delay=decision.delay_total_minutes)


def score(rows: list[Row]) -> dict:
    n = len(rows)
    outcomes = Counter(r.outcome for r in rows)
    automated = [r for r in rows if r.automated]
    auto_errors = [r for r in automated if r.outcome == WRONG]
    return {
        "n": n,
        "outcomes": {k: outcomes.get(k, 0) for k in (CORRECT, DEFERRED, WRONG)},
        "confusion": {e: {g: sum(1 for r in rows if r.expected_status == e and r.status == g)
                          for g in STATUSES} for e in STATUSES},
        "automated": len(automated),
        "automated_errors": len(auto_errors),
        "critical_errors": [r.case_id for r in rows if r.critical],
        "good_cases_dropped": [r.case_id for r in rows if r.good_case_dropped],
        "type_mismatches": [r.case_id for r in rows if r.type_mismatch],
        "wrong": [r.case_id for r in rows if r.outcome == WRONG],
        "deferred": [r.case_id for r in rows if r.outcome == DEFERRED],
    }


def _pct(k: int, n: int) -> str:
    return f"{k}/{n} ({100 * k / n:.0f} %)" if n else f"{k}/0 (-)"


def render(rows: list[Row], s: dict, versions: str) -> str:
    lines = [versions, ""]
    lines.append(f"{'cas':38} {'attendu':24} {'obtenu':24} {'action':18} {'expliqué':>9}  classe")
    for r in rows:
        exp = f"{r.expected_status}/{r.expected_type or '-'}"
        got = f"{r.status}/{r.ec_type or '-'}"
        lines.append(f"{r.case_id:38} {exp:24} {got:24} {r.action:18} "
                     f"{r.explained:>4}/{r.delay:<4}  {r.outcome}")

    lines += ["", "Matrice de confusion (lignes : attendu, colonnes : obtenu)",
              f"{'':14}" + "".join(f"{g:>13}" for g in STATUSES)]
    for e in STATUSES:
        lines.append(f"{e:14}" + "".join(f"{s['confusion'][e][g]:>13}" for g in STATUSES))

    n, o = s["n"], s["outcomes"]
    lines += [
        "",
        f"Corrects                      : {_pct(o[CORRECT], n)}",
        f"Renvoyés à un juriste         : {_pct(o[DEFERRED], n)}",
        f"Faux                          : {_pct(o[WRONG], n)}",
        f"Traités sans humain           : {_pct(s['automated'], n)}",
        f"Erreurs parmi les automatiques: {_pct(s['automated_errors'], s['automated'])}",
        f"  dont critiques (CONTINUER sur une CE plausible) : "
        f"{len(s['critical_errors'])} {s['critical_errors'] or ''}",
        f"  dont bons dossiers écartés (MISE_EN_ATTENTE sans CE) : "
        f"{len(s['good_cases_dropped'])} {s['good_cases_dropped'] or ''}",
        f"Type de CE différent          : {len(s['type_mismatches'])} {s['type_mismatches'] or ''}",
        "",
        f"Démonstration sur {n} dossiers construits à la main : pas une mesure statistique.",
    ]
    return "\n".join(lines)
