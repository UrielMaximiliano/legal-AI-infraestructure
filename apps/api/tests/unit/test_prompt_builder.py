"""Unit tests for prompt builder."""

from legal_ai.application.prompt_builder import PromptBuilder


class TestRenderTemplate:
    def test_render_employee_field(self):
        context = {"employee": {"first_name": "Juan"}}
        result = PromptBuilder.render_template(
            "Nombre: {{employee.first_name}}", context
        )
        assert result == "Nombre: Juan"

    def test_render_case_file_field(self):
        context = {"case_file": {"case_number": "CF-001"}}
        result = PromptBuilder.render_template(
            "Expediente: {{case_file.case_number}}", context
        )
        assert result == "Expediente: CF-001"

    def test_render_designation_field(self):
        context = {"designation": {"position_name": "Director"}}
        result = PromptBuilder.render_template(
            "Cargo: {{designation.position_name}}", context
        )
        assert result == "Cargo: Director"

    def test_render_variables_field(self):
        context = {"variables": {"custom": "valor"}}
        result = PromptBuilder.render_template("Custom: {{variables.custom}}", context)
        assert result == "Custom: valor"

    def test_render_unknown_namespace_preserved(self):
        context = {"employee": {"first_name": "Juan"}}
        result = PromptBuilder.render_template("Test: {{unknown.field}}", context)
        assert result == "Test: {{unknown.field}}"

    def test_render_multiple_variables(self):
        context = {
            "employee": {"first_name": "Juan"},
            "case_file": {"case_number": "CF-001"},
        }
        result = PromptBuilder.render_template(
            "{{employee.first_name}} - {{case_file.case_number}}", context
        )
        assert result == "Juan - CF-001"

    def test_render_empty_context(self):
        result = PromptBuilder.render_template("No variables", {})
        assert result == "No variables"


class TestBuildPrompt:
    def test_build_prompt_includes_instruction(self):
        context = {
            "case_file": {"case_number": "CF-001", "title": "Test"},
            "employee": {"first_name": "Juan", "last_name": "García"},
            "designation": {"position_name": "Director"},
        }
        result = PromptBuilder.build_prompt("Template body", context)
        assert "Genera un documento administrativo" in result
        assert "Template body" in result
        assert "CF-001" in result
        assert "Juan" in result
        assert "Director" in result

    def test_build_prompt_without_designation(self):
        context = {
            "case_file": {"case_number": "CF-001", "title": "Test"},
            "employee": {"first_name": "Juan", "last_name": "García"},
            "designation": {"position_name": ""},
        }
        result = PromptBuilder.build_prompt("body", context)
        assert "Designación" not in result


class TestValidateSyntax:
    def test_valid_syntax(self):
        unknown = PromptBuilder.validate_syntax(
            "{{employee.first_name}} {{case_file.case_number}}"
        )
        assert unknown == []

    def test_unknown_namespace(self):
        unknown = PromptBuilder.validate_syntax("{{unknown.field}}")
        assert "unknown.field" in unknown

    def test_valid_namespaces(self):
        unknown = PromptBuilder.validate_syntax(
            "{{employee.x}} {{case_file.y}} {{designation.z}} {{variables.a}}"
        )
        assert unknown == []

    def test_no_variables(self):
        unknown = PromptBuilder.validate_syntax("No variables here")
        assert unknown == []
