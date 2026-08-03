"""Prompt builder for Ollama generation."""

from __future__ import annotations

import re
from collections.abc import Mapping

PromptContext = Mapping[str, object]


class PromptBuilder:
    """Builds prompts for Ollama from templates and context."""

    SYSTEM_INSTRUCTION = (
        "Genera un documento administrativo basado en la siguiente plantilla "
        "y datos. Respetando el formato Markdown proporcionado."
    )

    @staticmethod
    def render_template(body_template: str, context: PromptContext) -> str:
        """Render template with context variables using Jinja2-like syntax."""
        rendered = body_template

        # Pattern: {{namespace.field}}
        pattern = r"\{\{(\w+)\.(\w+)\}\}"

        def replace_match(match: re.Match[str]) -> str:
            namespace = match.group(1)
            field = match.group(2)
            namespace_data = context.get(namespace, {})
            if isinstance(namespace_data, Mapping):
                value = namespace_data.get(field, match.group(0))
                return str(value) if value else match.group(0)
            return match.group(0)

        rendered = re.sub(pattern, replace_match, rendered)
        return rendered

    @staticmethod
    def build_prompt(rendered_template: str, context: PromptContext) -> str:
        """Build complete prompt with system instruction."""
        parts = [PromptBuilder.SYSTEM_INSTRUCTION, "", rendered_template]

        # Add context data
        cf = context.get("case_file")
        if isinstance(cf, Mapping):
            parts.append("")
            parts.append(
                f"Expediente: {cf.get('case_number', '')} - {cf.get('title', '')}"
            )

        emp = context.get("employee")
        if isinstance(emp, Mapping):
            parts.append(
                f"Empleado: {emp.get('first_name', '')} {emp.get('last_name', '')}"
            )

        desig = context.get("designation")
        if isinstance(desig, Mapping) and desig.get("position_name"):
            parts.append(f"Designación: {desig.get('position_name', '')}")

        return "\n".join(parts)

    @staticmethod
    def validate_syntax(body_template: str) -> list[str]:
        """Validate template syntax and return list of unknown variables."""
        pattern = r"\{\{(\w+)\.(\w+)\}\}"
        matches = re.findall(pattern, body_template)
        valid_namespaces = {"employee", "case_file", "designation", "variables"}
        unknown: list[str] = []
        for namespace, field in matches:
            if namespace not in valid_namespaces:
                unknown.append(f"{namespace}.{field}")
        return unknown
