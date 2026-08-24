#!/usr/bin/env python3
"""Apply deterministic layout and print fixes to a portable benchmark report."""

from __future__ import annotations

import argparse
import base64
import csv
import html as html_module
from pathlib import Path


STYLE = """
<style id="legal-ai-benchmark-layout-fixes">
  .benchmark-print-chart { display: none; }
  .benchmark-print-table { display: none; }
  .analytics-top-bar {
    width: 100% !important;
    margin-inline: 0 !important;
  }
  @media print {
    @page { size: A4 landscape; margin: 10mm; }
    html, body { background: #fff !important; }
    .analytics-top-bar, .analytics-sidebar, button { display: none !important; }
    [data-artifact-block-id="accuracy_chart"] { display: none !important; }
    [data-artifact-block-id="runs_table"] { display: none !important; }
    .benchmark-print-chart {
      display: block !important;
      break-inside: avoid;
      margin: 8mm 0 4mm;
    }
    .benchmark-print-chart h2 { margin: 0 0 3mm; }
    .benchmark-print-chart img {
      display: block;
      width: 100%;
      height: auto;
      max-height: 90mm;
      object-fit: contain;
    }
    .benchmark-print-chart p {
      margin: 2mm 0 0;
      color: #4b5563;
      font-size: 9pt;
    }
    .benchmark-print-table {
      display: block !important;
      break-inside: auto;
    }
    .benchmark-print-table h2 { margin: 0 0 3mm; }
    .benchmark-print-table table { font-size: 7.5pt !important; }
    .benchmark-print-table th,
    .benchmark-print-table td { padding: 1.4mm 1.8mm !important; }
    .analytics-app-shell, .analytics-main, .analytics-layout-canvas {
      display: block !important;
      width: 100% !important;
      max-width: none !important;
      margin: 0 !important;
      padding: 0 !important;
    }
    .panel, .chart-frame, .table-card {
      break-inside: avoid;
      box-shadow: none !important;
    }
    .table-scroll-container { overflow: visible !important; }
    .table-scroll-content, table { width: 100% !important; min-width: 0 !important; }
    table { font-size: 8pt !important; }
  }
</style>
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--print-chart-image", type=Path)
    parser.add_argument("--print-table-csv", type=Path)
    args = parser.parse_args()

    html = args.input.read_text(encoding="utf-8")
    if "legal-ai-benchmark-layout-fixes" in html:
        raise SystemExit("input report already contains the layout fixes")
    marker = "</head>"
    if marker not in html:
        raise SystemExit("portable report has no closing head tag")
    final = html.replace(marker, f"{STYLE}\n{marker}", 1)
    if args.print_chart_image:
        chart_bytes = args.print_chart_image.read_bytes()
        chart_b64 = base64.b64encode(chart_bytes).decode("ascii")
        chart_markup = (
            '<section class="benchmark-print-chart" aria-label="Fidelidad factual automática por configuración">'
            "<h2>Fidelidad factual automática por configuración</h2>"
            f'<img src="data:image/png;base64,{chart_b64}" alt="Accuracy automática de los 19 casos; 4B en azul y 0.6B en naranja">'
            "<p>Escala 0–100. C15 es el mayor valor observado; C09 es una corrida parcial y no participa del ranking.</p>"
            "</section>"
        )
        chart_marker = (
            '<div class="portable-block portable-layout-full" '
            'data-artifact-block-id="accuracy_chart"'
        )
        if chart_marker not in final:
            raise SystemExit("portable report has no accuracy chart block")
        final = final.replace(chart_marker, f"{chart_markup}\n{chart_marker}", 1)
    if args.print_table_csv:
        with args.print_table_csv.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        headers = (
            "Caso",
            "Modelo",
            "RAG",
            "Ollama",
            "k",
            "Pool",
            "Score",
            "Éxito",
            "Accuracy*",
            "Precision*",
            "Recall*",
        )
        body_rows: list[str] = []
        for row in rows:
            values = (
                row["case_id"],
                "4B" if "4b" in row["embedding_model"].lower() else "0.6B",
                row["rag_context"],
                row["ollama_context"],
                row["top_k"],
                row["candidate_pool"],
                f'{float(row["minimum_score"]):.2f}',
                f'{100 * float(row["success_rate"]):.1f}%',
                f'{100 * float(row["factual_fidelity_e2e"]):.2f}%',
                f'{100 * float(row["material_precision"]):.2f}%',
                f'{100 * float(row["material_recall"]):.2f}%',
            )
            cells = "".join(f"<td>{html_module.escape(value)}</td>" for value in values)
            body_rows.append(f"<tr>{cells}</tr>")
        table_markup = (
            '<section class="benchmark-print-table" aria-label="Las 19 configuraciones y sus resultados">'
            "<h2>Las 19 configuraciones y sus resultados</h2>"
            "<table><thead><tr>"
            + "".join(f"<th>{html_module.escape(header)}</th>" for header in headers)
            + "</tr></thead><tbody>"
            + "".join(body_rows)
            + "</tbody></table>"
            "<p>*Métricas automáticas; C09 es parcial y no participa del ranking.</p>"
            "</section>"
        )
        table_marker = (
            '<div class="portable-block portable-layout-full" '
            'data-artifact-block-id="runs_table"'
        )
        if table_marker not in final:
            raise SystemExit("portable report has no runs table block")
        final = final.replace(table_marker, f"{table_markup}\n{table_marker}", 1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(final, encoding="utf-8")
    print(f"report={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
