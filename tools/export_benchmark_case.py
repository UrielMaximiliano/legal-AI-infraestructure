"""Export one benchmark case as a compact, readable PDF."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)


def register_fonts() -> tuple[str, str]:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/calibri.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/calibrib.ttf"),
    ]
    regular = next(path for path in candidates if path.exists())
    bold = next(path for path in bold_candidates if path.exists())
    pdfmetrics.registerFont(TTFont("CaseRegular", str(regular)))
    pdfmetrics.registerFont(TTFont("CaseBold", str(bold)))
    return "CaseRegular", "CaseBold"


def paragraph(text: Any, style: ParagraphStyle) -> Paragraph:
    safe = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(safe, style)


def build(case: dict[str, Any], output_path: Path) -> None:
    regular, bold = register_fonts()
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "CaseTitle",
        parent=styles["Title"],
        fontName=bold,
        fontSize=19,
        leading=23,
        textColor=colors.HexColor("#172033"),
        alignment=TA_CENTER,
        spaceAfter=12,
    )
    heading = ParagraphStyle(
        "CaseHeading",
        parent=styles["Heading2"],
        fontName=bold,
        fontSize=12,
        leading=15,
        textColor=colors.HexColor("#172033"),
        spaceBefore=9,
        spaceAfter=5,
    )
    body = ParagraphStyle(
        "CaseBody",
        parent=styles["BodyText"],
        fontName=regular,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#172033"),
        spaceAfter=6,
    )
    small = ParagraphStyle(
        "CaseSmall",
        parent=body,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#596579"),
    )
    doc = BaseDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Salida LLM - Caso {case['case_number']:04d}",
    )
    doc.addPageTemplates(
        PageTemplate(
            id="case",
            frames=[Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height)],
        )
    )
    generated = case["output"]
    metadata = Table(
        [
            ["Caso", f"HOLDOUT-{case['case_number']:04d}"],
            ["Referencia", case["reference_pdf"]],
            ["Estado API", f"{case['status']} - HTTP {case['http_status']}"],
            ["Tiempo total", f"{case['total_ms'] / 1000:.3f} segundos"],
            ["Fuentes recuperadas", str(case["retrieved"])],
            ["Fuentes seleccionadas", str(case["selected"])],
        ],
        colWidths=[48 * mm, 112 * mm],
    )
    metadata.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), bold),
                ("FONTNAME", (1, 0), (1, -1), regular),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9E1EA")),
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#EAF0F8")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story: list[Any] = [
        paragraph("SALIDA GENERADA POR EL LLM", title),
        metadata,
        Spacer(1, 6 * mm),
        paragraph(generated["title"], heading),
        paragraph("VISTO", heading),
    ]
    for item in generated["visto"]:
        story.append(paragraph(f"{item['text']} [{', '.join(item['citation_ids'])}]", body))
    story.append(paragraph("CONSIDERANDO", heading))
    for item in generated["considerandos"]:
        story.append(paragraph(f"Que {item['text']} [{', '.join(item['citation_ids'])}]", body))
    story.extend(
        [
            paragraph(generated["dispositive_intro"], body),
            paragraph("PARTE DISPOSITIVA", heading),
        ]
    )
    for article in generated["articles"]:
        story.append(
            paragraph(
                f"ARTÍCULO {article['number']}°.- {article['text']} "
                f"[{', '.join(article['citation_ids'])}]",
                body,
            )
        )
    story.extend(
        [
            paragraph(generated["closing"], body),
            paragraph(f"Autoridad: {generated['authority']}", body),
            paragraph(f"Firma: {generated['signature']}", body),
            paragraph("ADVERTENCIAS", heading),
        ]
    )
    story.extend(paragraph(item, body) for item in generated["warnings"])
    story.append(paragraph("FUENTES RAG UTILIZADAS", heading))
    for source in generated["sources"]:
        story.append(
            paragraph(
                f"{source['citation_id']} - {source['title']} "
                f"({source['external_id']}, {source['publication_date']})",
                small,
            )
        )
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    case = json.loads(args.case.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build(case, args.output)


if __name__ == "__main__":
    main()
