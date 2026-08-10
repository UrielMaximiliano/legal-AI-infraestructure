# Checklist de calidad: Generación de Decretos Asistida por RAG

**Propósito**: validar que la especificación esté completa antes del planning
**Creado**: 2026-08-07
**Feature**: [spec.md](../spec.md)

## Calidad del contenido

- [x] Enfocada en valor, comportamiento y riesgos
- [x] Alcance y exclusiones explícitos
- [x] Todas las secciones obligatorias completas
- [x] Las restricciones técnicas mencionadas son decisiones contractuales previas

## Completitud de requisitos

- [x] No quedan marcadores `NEEDS CLARIFICATION`
- [x] Requisitos testables y no ambiguos
- [x] Criterios de éxito medibles
- [x] Escenarios primarios y fallos definidos
- [x] Casos límite identificados
- [x] Dependencias y supuestos documentados
- [x] Separación `INDEX_90` / `HOLDOUT_10` inequívoca

## Preparación

- [x] Cada flujo P1 tiene aceptación independiente
- [x] Seguridad, auditoría y revisión humana son fail-closed
- [x] La evaluación evita fuga del holdout
- [x] La especificación está lista para `$speckit-plan`

## Notas

- Validación completada en una iteración.
- La planificación deberá comprobar cuántos documentos de `INDEX_90` están realmente `REVIEWED` antes de habilitar pruebas E2E.
