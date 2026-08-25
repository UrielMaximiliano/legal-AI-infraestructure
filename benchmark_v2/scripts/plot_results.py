"""Create a small, dependency-free result plot or an honest placeholder."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _write_placeholder(output: Path, summary: dict[str, Any]) -> None:
    output.mkdir(parents=True, exist_ok=True)
    reason = "; ".join(summary.get("not_calculable_reasons") or ["no_calculable_metrics"])
    (output / "NOT_CALCULABLE.md").write_text(
        "# Gráficos V2\n\nNo se generó un gráfico de métricas porque la ejecución es "
        f"`{summary.get('status', 'NOT_CALCULABLE')}`.\n\nRazón: `{reason}`.\n",
        encoding="utf-8",
    )


def _write_svg(output: Path, summary: dict[str, Any]) -> None:
    dimensions = summary.get("dimensions", {})
    values = []
    for name, counts in dimensions.items():
        if not isinstance(counts, dict):
            continue
        value = counts.get("CALCULATED")
        if isinstance(value, (int, float)):
            values.append((str(name), float(value)))
    if not values:
        _write_placeholder(output, summary)
        return
    width, height = 900, 100 + 44 * len(values)
    maximum = max(value for _, value in values) or 1.0
    rows = []
    for index, (name, value) in enumerate(values):
        y = 40 + index * 44
        bar_width = 650 * value / maximum
        rows.append(
            f'<text x="12" y="{y + 18}" font-size="14">{name}</text>'
            f'<rect x="190" y="{y + 4}" width="{bar_width:.2f}" height="22" fill="#2f6690"/>'
            f'<text x="850" y="{y + 20}" text-anchor="end" font-size="14">{value:g}</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        '<text x="12" y="24" font-size="18" font-weight="bold">Casos calculables por dimensión</text>'
        + "".join(rows)
        + "</svg>"
    )
    output.mkdir(parents=True, exist_ok=True)
    (output / "dimension-calculability.svg").write_text(svg, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    if summary.get("status") == "NOT_CALCULABLE":
        _write_placeholder(args.output_dir, summary)
    else:
        _write_svg(args.output_dir, summary)
    print(f"plots={args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
