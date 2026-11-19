"""Tests du calcul des indicateurs, sur des lignes SYNTHÉTIQUES (sans réseau)."""

from ec_detector.evaluation import CORRECT, DEFERRED, WRONG, Row, render, score


def row(cid, exp, got, action, exp_type=None, got_type=None):
    return Row(cid, exp, exp_type, got, got_type, action)


ROWS = [
    row("ok_ec", "EC_PROBABLE", "EC_PROBABLE", "MISE_EN_ATTENTE", "METEO", "METEO"),
    row("ok_ec_juriste", "EC_PROBABLE", "EC_PROBABLE", "RELECTURE_JURISTE", "METEO", "METEO"),
    row("ok_aucune", "AUCUNE", "AUCUNE", "CONTINUER"),
    row("renvoye", "AUCUNE", "INCERTAIN", "RELECTURE_JURISTE"),
    row("critique", "EC_PROBABLE", "AUCUNE", "CONTINUER", "GREVE_ATC"),
    row("ecarte", "AUCUNE", "EC_PROBABLE", "MISE_EN_ATTENTE", None, "METEO"),
    row("mauvais_type", "EC_PROBABLE", "EC_PROBABLE", "MISE_EN_ATTENTE", "GREVE_ATC", "METEO"),
    row("doute_tranche", "INCERTAIN", "AUCUNE", "CONTINUER"),
]


def test_classes():
    by_id = {r.case_id: r.outcome for r in ROWS}
    assert by_id["ok_ec"] == by_id["ok_aucune"] == by_id["mauvais_type"] == CORRECT
    assert by_id["renvoye"] == DEFERRED
    assert by_id["critique"] == by_id["ecarte"] == by_id["doute_tranche"] == WRONG


def test_indicateurs():
    s = score(ROWS)
    assert s["n"] == 8
    assert s["outcomes"] == {CORRECT: 4, DEFERRED: 1, WRONG: 3}
    # Automatiques : ok_ec, ok_aucune, critique, ecarte, mauvais_type, doute_tranche.
    assert s["automated"] == 6 and s["automated_errors"] == 3
    # Un dossier douteux continué seul est aussi une erreur critique.
    assert s["critical_errors"] == ["critique", "doute_tranche"]
    assert s["good_cases_dropped"] == ["ecarte"]
    assert s["type_mismatches"] == ["mauvais_type"]
    assert s["confusion"]["EC_PROBABLE"]["AUCUNE"] == 1
    assert sum(sum(v.values()) for v in s["confusion"].values()) == 8


def test_rendu_sans_automatique():
    rows = [row("r", "AUCUNE", "INCERTAIN", "RELECTURE_JURISTE")]
    text = render(rows, score(rows), "v")
    assert "0/0 (-)" in text and "Démonstration sur 1 dossiers" in text
