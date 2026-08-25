from benchmark_v2.evaluators.legal_core import evaluate_case


def _case(text: str, *, sources=None):
    return {
        "case_number": 1,
        "external_id": "HOLDOUT-0001",
        "input": {"external_id": "HOLDOUT-0001", "prompt_text": "El organismo MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS debe prorrogar designaciones por 180 dias desde el 30 de diciembre de 2011."},
        "output": {"articles": [{"number": 1, "text": text, "citation_ids": ["SRC-001"]}]},
        "sources": sources or [{"citation_id": "SRC-001", "chunk_id": "c1", "score": 0.9}],
    }


def _gold():
    return {
        "reference_pdf": "x.pdf",
        "reference_sha256": "a" * 64,
        "field_candidates": {
            "organismo": "MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS",
            "objeto": "prorrogar designaciones",
            "fecha_plazo_vigencia": "30 de diciembre de 2011",
            "normas_citadas": ["1106 10"],
            "articulos_resolutivos": {"1": "prorrogar designaciones por CIENTO OCHENTA (180) dias"},
        },
    }


def test_correct_output_passes_core_and_tracks_source_ids():
    result = evaluate_case(
        _case("MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS prorroga designaciones por CIENTO OCHENTA (180) dias desde el 30 de diciembre de 2011, conforme Decreto N 1106/10."),
        _gold(),
    )
    assert result["legal_pass"] is True
    assert result["atomic_claims"]["recall"] == 1.0
    assert result["source_faithfulness"]["status"] == "NOT_RECONSTRUCTABLE"
    assert result["source_faithfulness"]["citation_traceability"] == 1.0


def test_amount_mutation_is_a_critical_contradiction():
    result = evaluate_case(_case("MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS prorroga designaciones por NOVENTA (90) dias desde el 30 de diciembre de 2011."), _gold())
    assert result["contradictions"]["critical_count"] >= 1
    assert result["legal_pass"] is False


def test_date_mutation_is_a_critical_contradiction():
    result = evaluate_case(_case("MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS prorroga designaciones por 180 dias desde el 31 de diciembre de 2011."), _gold())
    assert result["contradictions"]["critical_count"] >= 1
    assert result["legal_pass"] is False


def test_forbidden_closing_is_an_unsupported_addition():
    result = evaluate_case(_case("MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS prorroga designaciones por 180 dias. COMUNIQUESE, PUBLIQUESE y ARCHIVADO DIGITALMENTE."), _gold())
    assert result["unsupported_additions"]["count"] >= 1
    assert result["legal_pass"] is False


def test_citation_is_not_faithfulness_without_chunk_text():
    result = evaluate_case(_case("MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS prorroga designaciones por 180 dias.", sources=[{"citation_id": "SRC-001", "chunk_id": "c1"}]), _gold())
    assert result["source_faithfulness"]["status"] == "NOT_RECONSTRUCTABLE"


def test_identity_mutation_fails_the_critical_organism_field():
    gold = _gold()
    gold["field_candidates"]["organismo"] = "MINISTERIO DE JUSTICIA Y DERECHOS HUMANOS"
    result = evaluate_case(_case("MINISTERIO DE SALUD prorroga designaciones por 180 dias."), gold)
    assert result["critical_fields"]["fields"]["organismo"]["status"] == "FAIL"
    assert result["legal_pass"] is False


def test_authorize_to_prohibit_mutation_is_a_contradiction():
    gold = _gold()
    gold["field_candidates"]["objeto"] = "La autoridad autoriza el tramite"
    case = _case("La autoridad prohibe el tramite.")
    case["input"]["prompt_text"] = "La autoridad autoriza el tramite."
    result = evaluate_case(case, gold)
    assert result["contradictions"]["critical_count"] >= 1


def test_negation_mutation_is_a_contradiction():
    gold = _gold()
    gold["field_candidates"]["objeto"] = "No se autoriza el tramite"
    case = _case("Se autoriza el tramite.")
    case["input"]["prompt_text"] = "No se autoriza el tramite."
    result = evaluate_case(case, gold)
    assert result["contradictions"]["critical_count"] >= 1


def test_exception_mutation_is_an_omission():
    gold = _gold()
    gold["field_candidates"]["objeto"] = "Se permite el acceso salvo feriados"
    case = _case("Se permite el acceso.")
    case["input"]["prompt_text"] = "Se permite el acceso salvo feriados."
    result = evaluate_case(case, gold)
    assert result["omissions"]["critical_count"] >= 1
