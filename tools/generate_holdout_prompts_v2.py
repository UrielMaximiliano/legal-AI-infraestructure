"""Generate leakage-controlled natural-language prompts from holdout decrees.

The source PDF remains outside the prompt.  The output contains an internal
administrative request with enough facts to draft a decree, while excluding
the target decree number, its publication date, signatures, and PDF paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path

from pypdf import PdfReader


SEED = 20260812
VERSION = "holdout-prompt-v2"
FOOTER_RE = re.compile(
    r"https?://\S+|P[aá]gina\s+\d+|BOLET[IÍ]N\s+OFICIAL", re.IGNORECASE
)
TARGET_RE = re.compile(r"\bDecreto\s+(?:N[º°o.]\s*)?(\d{1,5}/\d{2,4})\b", re.IGNORECASE)
DATE_LINE_RE = re.compile(
    r"\b(?:Bs\.\s*As\.|(?:Ciudad de\s+)?Buenos Aires),?\s+\d{1,2}/\d{1,2}/\d{2,4}\b",
    re.IGNORECASE,
)
SIGNATURE_RE = re.compile(
    r"\b(?:Fdo\.?|Firmado|firma digital|certificado digital|refrendad[oa]|Ministro firmante)\b",
    re.IGNORECASE,
)
SECTION_END_RE = re.compile(r"\n\s*(?:Por ello,|LA PRESIDENTA|EL PRESIDENTE)", re.IGNORECASE)
ARTICLE_RE = re.compile(
    r"(?:Art[ií]culo|Art\.)\s*(\d+)[º°o.]?\s*(?:\.\s*)?[—-]\s*(.*?)(?=(?:\n\s*(?:Art[ií]culo|Art\.)\s*\d+)|\Z)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class Record:
    case_id: str
    prompt_file: str
    source_pdf: str
    source_sha256: str
    pages: int
    extracted_chars: int
    target_identifier_redacted: str
    organization: str
    objective: str
    facts: int
    operative_requirements: int
    quality_status: str


def squash(value: str) -> str:
    value = unicodedata.normalize("NFC", value.replace("\x00", " "))
    value = FOOTER_RE.sub(" ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip(" \n\t-—")


def sentence(value: str, max_chars: int = 620) -> str:
    value = squash(value)
    value = re.sub(r"^Que\s+", "", value, flags=re.IGNORECASE)
    value = SIGNATURE_RE.sub("[DATO EXCLUIDO]", value)
    if len(value) > max_chars:
        cut = value.rfind(". ", 0, max_chars)
        value = value[: cut + 1 if cut > 180 else max_chars].rstrip()
    return value[:1].upper() + value[1:] if value else value


def read_pdf(path: Path) -> tuple[str, int]:
    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return unicodedata.normalize("NFC", text), len(reader.pages)


def extract_target(text: str) -> str:
    match = TARGET_RE.search(text)
    return match.group(1) if match else "no-detectado"


def extract_organization(text: str) -> str:
    prefix = text[: TARGET_RE.search(text).start() if TARGET_RE.search(text) else 800]
    candidates = [squash(line) for line in prefix.splitlines() if squash(line)]
    candidates = [line for line in candidates if len(line) > 5]
    return candidates[-1] if candidates else "Organismo nacional competente"


def extract_objective(text: str) -> str:
    match = TARGET_RE.search(text)
    if not match:
        return "instrumentar una medida administrativa nacional debidamente fundada"
    tail = text[match.end() :]
    tail = DATE_LINE_RE.split(tail, maxsplit=1)[0]
    value = sentence(tail, 520)
    # Modern Boletín Oficial documents put a GDE identifier before the title.
    value = re.sub(r"^[A-Z]+-\d{4}-\d+-APN-[A-Z0-9#_-]+\s*-\s*", "", value, flags=re.IGNORECASE)
    substitutions = (
        (r"^Danse por prorrogadas?", "instrumentar la prórroga de"),
        (r"^Dase por prorrogada?", "instrumentar la prórroga de"),
        (r"^Desígnase", "instrumentar una designación en"),
        (r"^Designación", "instrumentar una designación"),
        (r"^Apruébase", "aprobar"),
        (r"^Créase", "crear"),
        (r"^Modifícase", "modificar"),
        (r"^Autorízase", "autorizar"),
    )
    for pattern, replacement in substitutions:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    value = value.rstrip(". ")
    return value[:1].lower() + value[1:] if value else value


def extract_visto(text: str) -> list[str]:
    start = re.search(r"\bVISTO\s*:?[ \t]*", text, re.IGNORECASE)
    if not start:
        return []
    body = text[start.end() :]
    end = re.search(
        r"\n\s*(?:CONSIDERANDO\s*:|Por ello,|LA PRESIDENTA|EL PRESIDENTE)",
        body,
        re.IGNORECASE,
    )
    if end:
        body = body[: end.start()]
    value = sentence(body, 900)
    return [f"El expediente y los antecedentes normativos relevantes comprenden: {value}"] if value else []


def extract_fallback_fact(text: str) -> list[str]:
    match = DATE_LINE_RE.search(text)
    body = text[match.end() :] if match else text
    body = re.split(
        r"\n\s*(?:LA PRESIDENTA|EL PRESIDENTE|Art[ií]culo\s+1|ART[IÍ]CULO\s+1)",
        body,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    body = re.split(r"\n\s*(?:Fecha de publicaci[oó]n|e\.\s+\d)", body, maxsplit=1, flags=re.IGNORECASE)[0]
    value = sentence(body, 900)
    return [f"La decisión debe considerar el siguiente fundamento y antecedente operativo: {value}"] if value else []


def extract_considerations(text: str) -> list[str]:
    start = re.search(r"CONSIDERANDO\s*:? ?", text, re.IGNORECASE)
    if not start:
        return extract_visto(text) or extract_fallback_fact(text)
    body = text[start.end() :]
    end = SECTION_END_RE.search(body)
    if end:
        body = body[: end.start()]
    parts = re.split(r"\n\s*Que\s+", "\n" + body, flags=re.IGNORECASE)
    facts = []
    for part in parts[1:]:
        value = sentence("Que " + part)
        if len(value) >= 35 and value not in facts:
            facts.append(value)
    # Preserve operational, budgetary, legal-review and competence facts.
    priority_terms = (
        "objeto", "razones", "solicita", "necesidad", "cargo", "estructura",
        "presupuesto", "crédito", "jurídic", "atribuciones", "facultades",
        "vigencia", "plazo", "selección", "designación", "servicio",
    )
    ranked = sorted(
        enumerate(facts),
        key=lambda item: (
            -sum(term.casefold() in item[1].casefold() for term in priority_terms),
            item[0],
        ),
    )
    selected = sorted(ranked[:8], key=lambda item: item[0])
    values = [value for _, value in selected]
    return values or extract_visto(text) or extract_fallback_fact(text)


def extract_articles(text: str) -> list[str]:
    requirements: list[str] = []
    for number, body in ARTICLE_RE.findall(text):
        value = sentence(body, 420)
        if not value or re.search(r"comun[ií]quese|publ[ií]quese|dese a la", value, re.IGNORECASE):
            continue
        transformations = (
            (r"^Danse por prorrogadas?", "Prorrogar"),
            (r"^Dase por prorrogada?", "Prorrogar"),
            (r"^Nómbrase,?\s*", "Disponer el nombramiento de "),
            (r"^Desígnase,?\s*", "Disponer la designación de "),
            (r"^Apruébase", "Aprobar"),
            (r"^Autorízase", "Autorizar"),
            (r"^Acéptase", "Aceptar"),
            (r"^Asígnase", "Asignar"),
            (r"^Incorpórase", "Incorporar"),
            (r"^Conviértese", "Convertir"),
            (r"^Derógase", "Derogar"),
            (r"^Facúltase", "Facultar"),
            (r"^Convócase", "Convocar"),
            (r"^Decláranse", "Declarar"),
        )
        for pattern, replacement in transformations:
            if re.search(pattern, value, re.IGNORECASE):
                value = re.sub(pattern, replacement, value, count=1, flags=re.IGNORECASE)
                break
        requirements.append(f"Artículo funcional {number}: {value}")
        if len(requirements) == 6:
            break
    return requirements


def ensure_operative_requirements(objective: str, articles: list[str]) -> list[str]:
    if articles:
        return articles
    if "promulg" in objective.casefold():
        return [
            f"Instrumentar la promulgación indicada en la intención administrativa: {objective}.",
            "Disponer las comunicaciones institucionales indispensables sin identificar autoridades firmantes.",
        ]
    return [
        f"Instrumentar de manera expresa la medida indicada: {objective}.",
        "Precisar su alcance, vigencia y autoridad de aplicación solamente cuando esos datos estén respaldados.",
    ]


def redact_target(value: str, target: str) -> str:
    if target == "no-detectado":
        return value
    number, year = target.split("/", 1)
    patterns = (
        rf"\bDecreto\s+(?:N[º°o.]\s*)?{re.escape(target)}\b",
        rf"\bDecreto\s+(?:N[º°o.]\s*)?{re.escape(number)}/{re.escape(year[-2:])}\b",
    )
    for pattern in patterns:
        value = re.sub(pattern, "la medida proyectada", value, flags=re.IGNORECASE)
    return value


def build_prompt(case_id: str, organization: str, objective: str, facts: list[str], articles: list[str], target: str) -> str:
    facts_text = "\n".join(f"- {redact_target(item, target)}" for item in facts) or "- La medida debe fundarse únicamente en los antecedentes recuperados y en los datos expresamente aportados."
    articles_text = "\n".join(f"- {redact_target(item, target)}" for item in articles) or "- Establecer con precisión la medida, su alcance, autoridad de aplicación, financiamiento y vigencia cuando corresponda."
    prompt = f"""# Solicitud interna de redacción normativa - {case_id}

## Intención administrativa

Necesito preparar un proyecto de decreto nacional para {redact_target(objective, target)}. El propósito es resolver esa necesidad administrativa con una medida jurídicamente fundada, operativamente aplicable y coherente con las competencias del organismo interviniente.

## Organismo y ámbito

La iniciativa corresponde a **{organization}**. Identificá en los antecedentes recuperados por el RAG la cadena orgánica, las competencias y el marco normativo que resulten pertinentes; no completes esos datos por analogía si no están respaldados.

## Hechos relevantes que deben orientar el proyecto

{facts_text}

## Resultado normativo esperado

La parte dispositiva debe resolver, como mínimo, los siguientes puntos funcionales:

{articles_text}

## Criterios de redacción y control

Redactá el proyecto en lenguaje jurídico-administrativo argentino, con encabezado descriptivo, VISTO, CONSIDERANDO, fórmula de autoridad y artículos numerados. La motivación debe conectar los antecedentes con la decisión y cada artículo debe contener una regla clara y ejecutable.

Usá el contexto recuperado por el sistema para fundamentar la competencia y los antecedentes. Toda afirmación proveniente del RAG debe citar una fuente permitida con el formato `SRC-NNN`. No cites este pedido ni menciones el proceso de recuperación.

No inventes números de expediente, normas, fechas, plazos, cargos, personas, documentos de identidad, montos, partidas presupuestarias, organismos ni anexos. Cuando falte un dato indispensable y no exista respaldo recuperado, escribí `[DATO PENDIENTE DE VALIDACIÓN]` en el lugar exacto donde deba completarse.

No incluyas nombres de autoridades firmantes, bloques de firma, certificados, firma digital, circuito de aprobación ni instrucciones para una futura persona firmante. Tampoco reproduzcas fórmulas de publicación o cierre administrativo que dependan de datos no provistos.

Entregá únicamente el proyecto de decreto. No agregues explicaciones, advertencias, análisis del proceso ni comentarios fuera del texto normativo.
"""
    return prompt.strip() + "\n"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--source-prompts", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    pdfs = sorted(args.pdf_dir.glob("*.pdf"))
    source_prompts = sorted(args.source_prompts.glob("prompt-*.md"))
    if len(pdfs) != 1000 or len(source_prompts) != 1000:
        raise SystemExit(f"Expected 1000 PDFs/prompts, found {len(pdfs)}/{len(source_prompts)}")

    args.output_dir.mkdir(parents=True, exist_ok=False)
    prompt_dir = args.output_dir / "prompts"
    prompt_dir.mkdir()
    records: list[Record] = []
    failures: list[dict[str, str]] = []

    for index, (pdf, source_prompt) in enumerate(zip(pdfs, source_prompts, strict=True), start=1):
        case_id = f"HOLDOUT-{index:04d}"
        try:
            text, pages = read_pdf(pdf)
            target = extract_target(text)
            organization = extract_organization(text)
            objective = extract_objective(text)
            facts = extract_considerations(text)
            articles = ensure_operative_requirements(objective, extract_articles(text))
            prompt = build_prompt(case_id, organization, objective, facts, articles, target)
            if target != "no-detectado" and re.search(re.escape(target), prompt, re.IGNORECASE):
                raise ValueError("target decree identifier leaked into prompt")
            if str(pdf) in prompt or pdf.name in prompt:
                raise ValueError("source path leaked into prompt")
            output_name = source_prompt.name
            (prompt_dir / output_name).write_text(prompt, encoding="utf-8", newline="\n")
            status = "PASS" if facts and articles and len(prompt) >= 1200 else "REVIEW"
            records.append(
                Record(
                    case_id=case_id,
                    prompt_file=output_name,
                    source_pdf=pdf.name,
                    source_sha256=sha256(pdf),
                    pages=pages,
                    extracted_chars=len(text),
                    target_identifier_redacted=target,
                    organization=organization,
                    objective=objective,
                    facts=len(facts),
                    operative_requirements=len(articles),
                    quality_status=status,
                )
            )
        except Exception as exc:  # keep a complete, auditable failure manifest
            failures.append({"case_id": case_id, "source_pdf": pdf.name, "error": type(exc).__name__})

    manifest = {
        "version": VERSION,
        "seed": SEED,
        "generation_method": "GPT-5.6-designed deterministic factual extraction and prompt template",
        "source_prompts_preserved": True,
        "count": len(records),
        "failures": len(failures),
        "quality": {
            "pass": sum(row.quality_status == "PASS" for row in records),
            "review": sum(row.quality_status == "REVIEW" for row in records),
        },
        "records": [asdict(row) for row in records],
        "failure_records": failures,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (args.output_dir / "manifest.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(asdict(records[0]).keys()) if records else ["case_id"])
        writer.writeheader()
        writer.writerows(asdict(row) for row in records)

    summary = (
        f"generated={len(records)} failures={len(failures)} "
        f"pass={sum(row.quality_status == 'PASS' for row in records)} "
        f"review={sum(row.quality_status == 'REVIEW' for row in records)}"
    )
    print(summary)
    if failures:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
