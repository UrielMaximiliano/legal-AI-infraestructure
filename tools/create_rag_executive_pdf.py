"""Create a stakeholder-ready PDF from a completed RAG benchmark."""

# ruff: noqa: E501 -- report copy remains readable as complete prose.

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

INK = colors.HexColor("#172033")
BLUE = colors.HexColor("#1D4ED8")
PALE_BLUE = colors.HexColor("#EAF0F8")
GREEN = colors.HexColor("#15803D")
AMBER = colors.HexColor("#B45309")
RED = colors.HexColor("#B91C1C")
MUTED = colors.HexColor("#596579")
LINE = colors.HexColor("#D9E1EA")


def pct(value: float) -> str:
    return f"{value:.1f}%"


def metric_table(items: list[tuple[str, str, str]]) -> Table:
    data: list[list[Any]] = []
    for label, value, note in items:
        data.append(
            [
                Paragraph(f"<b>{label}</b>", STYLES["MetricLabel"]),
                Paragraph(f"<b>{value}</b>", STYLES["MetricValue"]),
                Paragraph(note, STYLES["MetricNote"]),
            ]
        )
    table = Table(data, colWidths=[46 * mm, 42 * mm, 86 * mm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def score_bar(label: str, value: float, explanation: str) -> KeepTogether:
    color = GREEN if value >= 80 else colors.HexColor("#CA8A04") if value >= 60 else AMBER if value >= 40 else RED
    bar = Table(
        [["", ""]],
        colWidths=[max(0.1, 174 * value / 100) * mm, max(0.1, 174 * (100 - value) / 100) * mm],
        rowHeights=[5 * mm],
    )
    bar.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), color),
                ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#E5E7EB")),
                ("BOX", (0, 0), (-1, -1), 0, colors.white),
            ]
        )
    )
    return KeepTogether(
        [
            Paragraph(f"<b>{label}: {pct(value)}</b>", STYLES["Body"]),
            bar,
            Spacer(1, 2 * mm),
            Paragraph(explanation, STYLES["Small"]),
            Spacer(1, 4 * mm),
        ]
    )


def page_chrome(canvas: Any, doc: Any) -> None:
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 17 * mm, 192 * mm, 17 * mm)
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 11 * mm, "Benchmark RAG legal - Configuracion 8.192 tokens")
    canvas.drawRightString(192 * mm, 11 * mm, f"Pagina {doc.page}")
    canvas.restoreState()


def build_report(summary: dict[str, Any], rows: list[dict[str, str]], output: Path) -> None:
    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=19 * mm,
        bottomMargin=22 * mm,
        title="Evaluacion ejecutiva del asistente juridico",
        author="Legal AI Benchmark",
        subject="Benchmark de 1.000 decretos con RAG y Ollama",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=page_chrome))

    total = int(summary["cases"])
    succeeded = sum(row["status"] == "SUCCEEDED" for row in rows)
    failed = total - succeeded
    story: list[Any] = [
        Paragraph("Evaluacion ejecutiva del asistente juridico", STYLES["ExecTitle"]),
        Paragraph(
            "Benchmark de 1.000 solicitudes de decretos comparadas contra sus PDF oficiales de referencia",
            STYLES["ExecSubtitle"],
        ),
        Spacer(1, 7 * mm),
        Table(
            [[Paragraph("DIAGNOSTICO", STYLES["Label"]), Paragraph("Requiere mejoras antes de produccion", STYLES["Verdict"])]],
            colWidths=[35 * mm, 139 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (0, 0), INK),
                    ("BACKGROUND", (1, 0), (1, 0), colors.HexColor("#FFF7ED")),
                    ("BOX", (0, 0), (-1, -1), 0.8, AMBER),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, -1), 12),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
                ]
            ),
        ),
        Spacer(1, 7 * mm),
        Paragraph("Resumen ejecutivo", STYLES["H1"]),
        Paragraph(
            f"El sistema completo {succeeded} de {total} solicitudes con una respuesta tecnicamente valida ({pct(summary['technical_success_rate'])}). "
            "Las respuestas conservan muy bien la forma juridica y utilizan citas verificables, pero todavia presentan baja coincidencia con los hechos, normas, nombres y fechas del decreto original.",
            STYLES["Body"],
        ),
        Spacer(1, 3 * mm),
        Paragraph(
            "La conclusion empresarial es clara: la arquitectura RAG funciona y ya permite experimentar de manera reproducible, pero la configuracion actual debe mantenerse como asistente de borradores con revision humana obligatoria. No debe utilizarse todavia para emitir documentos finales de manera autonoma.",
            STYLES["Body"],
        ),
        Spacer(1, 6 * mm),
        metric_table(
            [
                ("Casos evaluados", f"{total:,}".replace(",", "."), "Cobertura completa del holdout reservado."),
                ("Exito tecnico", pct(summary["technical_success_rate"]), f"{succeeded} validos y {failed} fallidos."),
                ("Calidad integral", pct(summary["accuracy_end_to_end"]), "Incluye fallos tecnicos con puntaje cero."),
                ("Calidad cuando responde", pct(summary["accuracy_average"]), "Solo considera las respuestas estructuralmente validas."),
                ("Latencia mediana", f"{summary['latency_p50_ms'] / 1000:.1f} s", "La mitad de los casos termino por debajo de este tiempo."),
                ("Latencia p95", f"{summary['latency_p95_ms'] / 1000:.1f} s", "El 95% termino por debajo de este tiempo."),
            ]
        ),
        PageBreak(),
        Paragraph("El formato juridico es fuerte; la fidelidad factual es el principal riesgo", STYLES["H1"]),
        Paragraph(
            "Las barras separan la calidad formal de la calidad sustantiva. Una estructura correcta no significa que los datos juridicos coincidan con el decreto oficial.",
            STYLES["Body"],
        ),
        Spacer(1, 5 * mm),
        score_bar("Estructura juridica", summary["structure_average"] * 100, "Respeta secciones y forma esperada de un decreto."),
        score_bar("Citas validas", summary["citation_validity_average"] * 100, "Las citas utilizadas pertenecen al contexto recuperado."),
        score_bar("Contenido coincidente", summary["content_f1_average"] * 100, "Similitud del contenido generado respecto del documento oficial."),
        score_bar("Fidelidad al pedido", summary["prompt_fidelity_average"] * 100, "Cobertura de los elementos solicitados en el prompt."),
        score_bar("Hechos y normas coincidentes", summary["entity_f1_average"] * 100, "Coincidencia de personas, organismos, fechas y referencias normativas."),
        Spacer(1, 3 * mm),
        Paragraph("Implicacion", STYLES["H2"]),
        Paragraph(
            "El sistema puede acelerar la preparacion de una estructura inicial, pero un profesional debe verificar y corregir cada dato juridico antes de utilizar el borrador.",
            STYLES["Body"],
        ),
        PageBreak(),
        Paragraph("El 43,4% de los casos fallo antes de producir un borrador utilizable", STYLES["H1"]),
        Paragraph(
            "Los errores de salida del modelo y los problemas de auditoria se muestran por separado porque requieren soluciones diferentes.",
            STYLES["Body"],
        ),
        Spacer(1, 5 * mm),
        metric_table(
            [
                ("Salida invalida", "424", "El modelo no cumplio el esquema JSON aun despues del intento de reparacion."),
                ("Auditoria no disponible", "10", "La politica fail-closed impidio devolver resultados sin registrar la busqueda."),
                ("Total de fallos", str(failed), pct(100 * failed / total) + " del benchmark completo."),
            ]
        ),
        Spacer(1, 8 * mm),
        Paragraph("Lectura correcta de precision y cobertura", STYLES["H2"]),
        Paragraph(
            f"La precision lexica aproximada fue {pct(summary['precision_at_5_proxy_average'] * 100)}, mientras que la cobertura fue {pct(summary['recall_at_5_proxy_average'] * 100)}. "
            "Esto sugiere que lo recuperado suele ser pertinente, pero cubre solo una parte limitada de la informacion presente en el decreto original.",
            STYLES["Body"],
        ),
        Paragraph(
            "Estas son metricas automaticas basadas en coincidencia de texto. No equivalen a una evaluacion juridica humana de relevancia y no deben presentarse como precision legal definitiva.",
            STYLES["Callout"],
        ),
        PageBreak(),
        Paragraph("Recomendacion: mejorar validez estructurada y recuperacion antes de escalar", STYLES["H1"]),
        Paragraph("Plan recomendado", STYLES["H2"]),
        Paragraph(
            "1. Instrumentar causas sanitizadas por campo para distinguir JSON invalido, campos faltantes y citas desconocidas.<br/>"
            "2. Reejecutar los 424 casos de salida invalida con un prompt de reparacion mejorado.<br/>"
            "3. Corregir los 10 fallos de auditoria y repetirlos en forma aislada.<br/>"
            "4. Mejorar la consulta y seleccion de contexto para elevar la cobertura sin perder precision.<br/>"
            "5. Etiquetar humanamente una muestra estratificada y medir relevancia juridica real.<br/>"
            "6. Comparar una segunda configuracion utilizando exactamente los mismos 1.000 prompts y PDF.",
            STYLES["Body"],
        ),
        Spacer(1, 7 * mm),
        Paragraph("Criterios sugeridos para la proxima iteracion", STYLES["H2"]),
        metric_table(
            [
                ("Exito tecnico", ">= 90%", "Reducir respuestas descartadas por el esquema."),
                ("Fidelidad factual", ">= 60%", "Validar el objetivo con una muestra revisada por expertos."),
                ("Cobertura", ">= 50%", "Recuperar mas antecedentes relevantes sin degradar precision."),
                ("Uso operativo", "Revisado", "Mantener aprobacion humana obligatoria hasta superar gates."),
            ]
        ),
        PageBreak(),
        Paragraph("Alcance y configuracion del benchmark", STYLES["H1"]),
        metric_table(
            [
                ("Modelo generador", "qwen3.6:35b", "Servidor Ollama con GPU RTX 5090."),
                ("Modelo de embeddings", "Qwen3 Embedding 4B", "Vectores de 2.560 dimensiones."),
                ("Ventana de contexto", "8.192 tokens", "Configuracion elegida por benchmark previo."),
                ("Recuperacion", "Top 8", "Busqueda exacta sobre pgvector."),
                ("Corpus", "9.000 decretos", "65.916 fragmentos vectorizados."),
                ("Holdout", "1.000 PDF", "Reservados y no vectorizados; usados solo como referencia."),
                ("Inferencia", "1 simultanea", "Ejecucion secuencial para comparabilidad y estabilidad."),
            ]
        ),
        Spacer(1, 7 * mm),
        Paragraph("Metodologia", STYLES["H2"]),
        Paragraph(
            "Cada prompt se envio a la API RAG. La API recupero antecedentes desde pgvector y solicito al modelo generador un decreto estructurado. La salida se guardo incrementalmente. Luego, fuera del servidor, cada respuesta se comparo contra su PDF oficial correspondiente. Los PDF originales nunca se entregaron al modelo.",
            STYLES["Body"],
        ),
        Paragraph("Limitaciones", STYLES["H2"]),
        Paragraph(
            "El puntaje integral es una metrica compuesta para comparar configuraciones y no una certificacion juridica. Las metricas de recuperacion son proxies lexicos. La fidelidad definitiva requiere evaluacion humana, criterios de relevancia documentados y revision de una muestra representativa.",
            STYLES["Body"],
        ),
        Spacer(1, 8 * mm),
        Paragraph("Conclusion", STYLES["H2"]),
        Paragraph(
            "El experimento valida la viabilidad tecnica del flujo RAG, pero tambien demuestra por que la revision humana y la medicion sistematica son indispensables. La siguiente inversion debe enfocarse en validez estructurada, cobertura y fidelidad factual, no solamente en aumentar el tamano del modelo.",
            STYLES["Callout"],
        ),
    ]
    doc.build(story)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    with args.csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    build_report(summary, rows, args.output)


STYLES = getSampleStyleSheet()
STYLES.add(ParagraphStyle(name="ExecTitle", parent=STYLES["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=INK, alignment=TA_LEFT, spaceAfter=8))
STYLES.add(ParagraphStyle(name="ExecSubtitle", parent=STYLES["Normal"], fontName="Helvetica", fontSize=12, leading=17, textColor=MUTED))
STYLES.add(ParagraphStyle(name="H1", parent=STYLES["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK, spaceBefore=5, spaceAfter=9))
STYLES.add(ParagraphStyle(name="H2", parent=STYLES["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK, spaceBefore=5, spaceAfter=6))
STYLES.add(ParagraphStyle(name="Body", parent=STYLES["BodyText"], fontName="Helvetica", fontSize=10, leading=15, textColor=INK, spaceAfter=7))
STYLES.add(ParagraphStyle(name="Small", parent=STYLES["BodyText"], fontName="Helvetica", fontSize=8.5, leading=12, textColor=MUTED))
STYLES.add(ParagraphStyle(name="MetricLabel", parent=STYLES["BodyText"], fontName="Helvetica", fontSize=9, leading=12, textColor=INK))
STYLES.add(ParagraphStyle(name="MetricValue", parent=STYLES["BodyText"], fontName="Helvetica-Bold", fontSize=13, leading=15, textColor=BLUE, alignment=TA_CENTER))
STYLES.add(ParagraphStyle(name="MetricNote", parent=STYLES["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11, textColor=MUTED))
STYLES.add(ParagraphStyle(name="Label", parent=STYLES["BodyText"], fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.white, alignment=TA_CENTER))
STYLES.add(ParagraphStyle(name="Verdict", parent=STYLES["BodyText"], fontName="Helvetica-Bold", fontSize=14, leading=17, textColor=AMBER))
STYLES.add(ParagraphStyle(name="Callout", parent=STYLES["BodyText"], fontName="Helvetica-Bold", fontSize=10, leading=15, textColor=INK, backColor=PALE_BLUE, borderColor=BLUE, borderWidth=0.8, borderPadding=9, spaceBefore=7, spaceAfter=7))


if __name__ == "__main__":
    main()
