"""Note pour le juriste : les garde-fous autour du LLM (D14). Sans réseau : LLM simulé."""

import json

from ec_detector.note import (LLM, MODELE_FIXE, build_facts, check_note, fixed_paragraphs,
                              write_note)

DEC = {
    "case_id": "dossier-1",
    "status": "EC_PROBABLE",
    "action": "RELECTURE_JURISTE",
    "ec_type": "METEO",
    "ec_types": ["METEO"],
    "confidence": 0.9,
    "delay_total_minutes": 1470,
    "delay_explained_minutes": 555,
    "remaining_delay_minutes": 915,
    "fully_explained": False,
    "reasons": [
        "Météo grave à LFRB (départ) : 90 min sévères, de 02/11 02:30Z à 02/11 10:00Z.",
        "La CE n'explique qu'environ 555 min sur 1470 : il reste 915 min, au-dessus du seuil de 180 min.",
    ],
    "evidence": [
        {"airport": "LFRB", "role": "départ", "observed_at": "2023-11-02T02:30:00+00:00",
         "raw": "LFRB 020230Z AUTO 26045G75KT 2700 RA BR",
         "signals": [{"rule_id": "wind.severe_gust_kt", "severity": "severe",
                      "value": "75 kt", "threshold": ">= 50 kt"}],
         "source": "METAR"},
    ],
    "flight": {"number": "TEST002", "departure": "LFRB", "arrival": "LFPG",
               "scheduled_departure": "2023-11-02T05:30:00+00:00",
               "scheduled_arrival": "2023-11-02T06:45:00+00:00",
               "actual_departure": "2023-11-03T06:00:00+00:00",
               "actual_arrival": "2023-11-03T07:15:00+00:00"},
    "legal_regime": "CE_261_2004",
    "rules_version": "0.2.0",
    "computed_at": "2026-11-19T10:00:00+00:00",
}


def answer(*paragraphs):
    return lambda messages: json.dumps(
        {"paragraphes": [{"texte": t, "refs": r} for t, r in paragraphs]}, ensure_ascii=False)


GOOD = answer(
    ("Le dossier part en relecture juriste : la CE n'explique que 555 min sur 1470.", ["R2"]),
    ("Rafales de 75 kt relevées à LFRB (départ).", ["R1", "E1"]),
)


def test_note_llm_acceptee():
    n = write_note(DEC, GOOD, model="m")
    assert n["source"] == LLM and n["model"] == "m" and n["fallback_reason"] is None
    assert [p["refs"] for p in n["paragraphs"]] == [["R2"], ["R1", "E1"]]
    assert n["references"]["E1"].startswith("METAR LFRB")


def test_reference_inventee_rejetee():
    n = write_note(DEC, answer(("Grève confirmée à Brest.", ["E7"])))
    assert n["source"] == MODELE_FIXE
    assert any("E7" in p for p in n["llm_problems"])


def test_nombre_invente_rejete():
    # 24 h n'est pas dans les faits : le LLM a converti (interdit), on rejette.
    n = write_note(DEC, answer(("Le retard est d'environ 24 h.", ["R2"])))
    assert n["source"] == MODELE_FIXE
    assert any("« 24 »" in p for p in n["llm_problems"])


def test_paragraphe_sans_preuve_rejete():
    n = write_note(DEC, answer(("La compagnie est responsable.", [])))
    assert n["source"] == MODELE_FIXE and any("aucune preuve" in p for p in n["llm_problems"])


def test_reponse_non_json_ou_erreur_reseau():
    assert write_note(DEC, lambda m: "Voici la note : ...")["source"] == MODELE_FIXE

    def down(messages):
        raise ConnectionError("réseau indisponible")
    n = write_note(DEC, down)
    assert n["source"] == MODELE_FIXE and "réseau" in n["llm_problems"][0]


def test_sans_llm_modele_fixe_qui_passe_ses_propres_controles():
    n = write_note(DEC, None)
    assert n["source"] == MODELE_FIXE and "MISTRAL_API_KEY" in n["fallback_reason"]
    assert check_note(n["paragraphs"], build_facts(DEC)) == []


def test_le_llm_ne_recoit_que_les_faits():
    seen = {}

    def spy(messages):
        seen["messages"] = messages
        return GOOD(messages)
    write_note(DEC, spy)
    user = seen["messages"][1]["content"]
    assert "LFRB 020230Z" in user and "R1" in user and "E1" in user
    assert "computed_at" not in user          # seulement les faits utiles, pas tout le JSON


def test_preuves_tronquees_et_comptees():
    dec = dict(DEC, evidence=DEC["evidence"] * 25)
    facts = build_facts(dec, max_evidence=20)
    assert len(facts["preuves"]) == 20 and facts["preuves_non_envoyees"] == 5
    assert check_note(fixed_paragraphs(facts), facts) == []


def test_preuves_equilibrees_entre_aeroports_et_numeros_stables():
    dep = dict(DEC["evidence"][0])
    arr = dict(dep, airport="LFPG", role="arrivée")
    dec = dict(DEC, evidence=[dep] * 30 + [arr] * 5)   # arrivée en fin de liste
    facts = build_facts(dec, max_evidence=10)
    airports = [e["aeroport"] for e in facts["preuves"].values()]
    assert airports.count("LFPG") == 5 and airports.count("LFRB") == 5
    assert "E31" in facts["preuves"]                   # numéro = position dans la décision


def test_cache_disque_et_quota_jamais_garde(tmp_path):
    from ec_detector.note import NoteStore, note_for
    calls = []

    def quota(messages):
        calls.append(1)
        raise RuntimeError("quota Mistral atteint")
    store = NoteStore(tmp_path)
    n = note_for(DEC, quota, "m", store)
    assert n["source"] == MODELE_FIXE and n["retryable"] and not list(tmp_path.iterdir())

    def ok(messages):
        calls.append(1)
        return GOOD(messages)
    assert note_for(DEC, ok, "m", store)["source"] == LLM
    # Nouveau magasin sur le même dossier (redémarrage du serveur) : servi par le disque.
    again = note_for(dict(DEC, computed_at="plus tard"), ok, "m", NoteStore(tmp_path))
    assert again["from_cache"] and again["source"] == LLM and len(calls) == 2


def test_note_rejetee_non_retentable():
    n = write_note(DEC, answer(("Retard de 24 h.", ["R2"])))
    assert n["source"] == MODELE_FIXE and n["retryable"] is False


def test_normalisation_de_forme_seulement():
    from ec_detector.note import normalize_refs
    assert normalize_refs(["raisons.R3", " e2 ", "preuves.E1-E3", "R3"]) == ["R3", "E2", "E1", "E3"] \
        or normalize_refs(["raisons.R3", " e2 ", "preuves.E1-E3", "R3"]) == ["R3", "E2", "E1", "E3"]
    # une forme corrigée qui n'existe pas reste refusée
    n = write_note(DEC, answer(("Décision du moteur.", ["decision.D1"]),
                               ("Rafales à LFRB.", ["preuves.E1-E2"])))
    assert n["source"] == MODELE_FIXE and any("E2" in p for p in n["llm_problems"])


def test_d1_v1_citables():
    n = write_note(DEC, answer(("Vol TEST002, relecture juriste.", ["D1", "V1"])))
    assert n["source"] == LLM


# Erreurs réellement produites par ministral-8b pendant la mise au point (D14).
def test_inversion_de_la_decision_rejetee():
    n = write_note(DEC, answer(("La décision confirme une indemnisation probable.", ["D1"])))
    assert n["source"] == MODELE_FIXE
    assert any("contredit le sens" in p for p in n["llm_problems"])


def test_mauvais_nom_d_aeroport_rejete():
    n = write_note(DEC, answer(("Arrivée à LFPG (Paris-Orly).", ["V1"])))
    assert any("Orly" in p for p in n["llm_problems"])
    n = write_note(DEC, answer(("Déroutement vers LFPO.", ["V1"])))
    assert any("LFPO" in p for p in n["llm_problems"])


def test_bon_nom_et_sens_fidele_acceptes():
    n = write_note(DEC, answer(
        ("Une circonstance extraordinaire est probable : la compagnie pourrait refuser l'indemnité. "
         "Arrivée à LFPG (Paris-Charles de Gaulle), code OACI.", ["D1", "V1"]),
        ("Aucune circonstance extraordinaire confirmée sur les 915 min restantes.", ["R2"])))
    assert n["source"] == LLM, n["llm_problems"]


def test_gras_markdown_retire():
    n = write_note(DEC, answer(("**Relecture juriste** demandée.", ["D1"])))
    assert n["paragraphs"][0]["text"] == "Relecture juriste demandée."


def test_negation_non_prise_pour_une_inversion():
    calme = dict(DEC, status="AUCUNE", action="CONTINUER")
    for phrase in ("Le moteur ne relève pas de circonstance extraordinaire probable.",
                   "Absence de circonstance extraordinaire confirmée aux deux aéroports."):
        n = write_note(calme, answer((phrase, ["D1"])))
        assert n["source"] == LLM, n["llm_problems"]
    n = write_note(calme, answer(("Une circonstance extraordinaire est probable.", ["D1"])))
    assert n["source"] == MODELE_FIXE


def test_cause_hors_perimetre_rejetee():
    n = write_note(DEC, answer(("Aucune grève du personnel navigant n'a été relevée.", ["R1"])))
    assert any("personnel navigant" in p for p in n["llm_problems"])


def test_duree_en_heures_rejetee_mais_pas_les_horaires():
    # Erreur réelle : « 9 heures et 35 minutes » passait le contrôle des nombres (9 et 35 sont dans les METAR).
    n = write_note(DEC, answer(("Il reste 9 heures et 35 minutes.", ["R2"])))
    assert any("heures" in p for p in n["llm_problems"])
    n = write_note(DEC, answer(("Départ prévu à 05:30Z, soit 05h30.", ["V1"])))
    assert n["source"] == LLM, n["llm_problems"]
