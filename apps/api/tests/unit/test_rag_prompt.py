"""Unit tests for the IMI structured-generation prompt contract."""

from legal_ai.application.rag_prompt import RagPromptBuilder


def test_nota_inicio_prompt_forbids_articles_and_uses_official_title() -> None:
    prompt = RagPromptBuilder().build(
        query="Generar nota de inicio",
        context="SRC-001: normativa oficial",
        variables={
            "expediente": "139-000123/2026",
            "fecha": "2026-08-28",
            "beneficiario": "Ivan Rodriguez",
            "concepto": "Becarios",
        },
        document_type="nota_inicio",
        template_body="INFORME DE INICIO DE ACTUACIONES",
    )

    assert "title debe ser 'INFORME DE INICIO DE ACTUACIONES'" in prompt.system_message
    assert "articles debe ser []" in prompt.system_message
    assert "No agregues VISTO" in prompt.system_message
    assert "warnings debe contener exactamente una" in prompt.system_message


def test_disposicion_prompt_requires_six_articles() -> None:
    prompt = RagPromptBuilder().build(
        query="Generar disposición",
        context="SRC-001: normativa oficial",
        variables={"fecha": "2026-08-28"},
        document_type="disposicion",
        template_body="DISPOSICIÓN N.º {{numero}}/2026",
    )

    assert "exactamente seis artículos numerados del 1 al 6" in prompt.system_message
