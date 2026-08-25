# Reconciliación V1 y descubrimiento de outputs

El catálogo histórico V1 describe 19 configuraciones de 1.000 casos. El
snapshot real de `pc-rtx5090` contiene el manifiesto de 1.000 prompts, 1.000
gold facts y la corrida C03 completa (`benchmark-1000-8192-v4`): 1.000 case
files, 1.000 registros JSONL, 1.000 filas CSV, todos `SUCCEEDED`, sin
desacuerdos de PDF/SHA-256.

El reconciliador informa `WARN`, no `FAIL`: el artefacto V1 de performance
(`004-benchmark-v1`) tiene un digest de fixture diferente al fixture actual.
Ese artefacto se conserva como evidencia histórica de latencia, pero no se
usa para declarar fidelidad jurídica ni se mezcla con los outputs C02/C03.

- [Inventario remoto generado](../../benchmark_v2/results/remote-artifact-inventory-20260825/artifact_inventory.md)
- [Reconciliación JSON](../../benchmark_v2/reports/v1-reconciliation.json)
- [Script de reconciliación](../../benchmark_v2/scripts/reconcile_v1_reports.py)

El inventario local sólo muestra como corrida completa el subárbol C03 porque
el snapshot de trabajo se copió selectivamente; C02 se evaluó por separado a
partir de sus 1.000 case files y mantiene join `FULL` contra el mismo gold.
