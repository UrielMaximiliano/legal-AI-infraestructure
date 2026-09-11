"""Dominio puro para candidatos de placeholders DOCX.

Sin E/S, sin logging y sin IA. Solo tipos, normalización determinista e
inferencia de formato. La confirmación/publicación es siempre humana.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import StrEnum


class PlaceholderOrigin(StrEnum):
    """Origen estructural del texto que contiene el candidato."""

    PARAGRAPH = "PARAGRAPH"
    TABLE_CELL = "TABLE_CELL"
    HEADER = "HEADER"
    FOOTER = "FOOTER"


class PlaceholderSyntax(StrEnum):
    """Sintaxis textual o control nativo que originó el candidato."""

    DOUBLE_BRACE = "DOUBLE_BRACE"
    SINGLE_BRACE = "SINGLE_BRACE"
    BRACKET = "BRACKET"
    DOUBLE_ANGLE = "DOUBLE_ANGLE"
    COMPLETAR = "COMPLETAR"
    BLANK = "BLANK"
    ELLIPSIS = "ELLIPSIS"
    NATIVE_SDT = "NATIVE_SDT"
    NATIVE_MERGEFIELD = "NATIVE_MERGEFIELD"
    NATIVE_FORMFIELD = "NATIVE_FORMFIELD"


class PlaceholderStatus(StrEnum):
    """Estados del ciclo de vida humano del candidato."""

    DETECTED = "DETECTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISCARDED = "DISCARDED"


class FieldKind(StrEnum):
    """Tipo/formato inferido de forma heurística y determinista."""

    TEXT = "TEXT"
    DATE = "DATE"
    NUMBER = "NUMBER"
    CURRENCY = "CURRENCY"
    EMAIL = "EMAIL"
    CHECKBOX = "CHECKBOX"


_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VALID_KEY_CHARS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\-]*$")
_CONFIDENCE: dict[PlaceholderSyntax, float] = {
    PlaceholderSyntax.DOUBLE_BRACE: 0.95,
    PlaceholderSyntax.DOUBLE_ANGLE: 0.90,
    PlaceholderSyntax.NATIVE_SDT: 0.90,
    PlaceholderSyntax.NATIVE_MERGEFIELD: 0.90,
    PlaceholderSyntax.NATIVE_FORMFIELD: 0.85,
    PlaceholderSyntax.SINGLE_BRACE: 0.80,
    PlaceholderSyntax.BRACKET: 0.80,
    PlaceholderSyntax.COMPLETAR: 0.60,
    PlaceholderSyntax.BLANK: 0.55,
    PlaceholderSyntax.ELLIPSIS: 0.40,
}

_EXPLANATIONS: dict[PlaceholderSyntax, str] = {
    PlaceholderSyntax.DOUBLE_BRACE: "Sintaxis {{campo}} explícita de plantilla.",
    PlaceholderSyntax.SINGLE_BRACE: "Sintaxis {campo} de llave simple.",
    PlaceholderSyntax.BRACKET: "Sintaxis [campo] entre corchetes.",
    PlaceholderSyntax.DOUBLE_ANGLE: "Sintaxis <<campo>> de plantilla heredada.",
    PlaceholderSyntax.COMPLETAR: "Marca genérica [COMPLETAR] pendiente de redacción.",
    PlaceholderSyntax.BLANK: "Blanco con guiones bajos pendiente de completar.",
    PlaceholderSyntax.ELLIPSIS: "Puntos suspensivos usados como blanco.",
    PlaceholderSyntax.NATIVE_SDT: "Control estructurado nativo (w:sdt) del documento.",
    PlaceholderSyntax.NATIVE_MERGEFIELD: "Campo MERGEFIELD nativo de Word.",
    PlaceholderSyntax.NATIVE_FORMFIELD: "Campo de formulario heredado de Word.",
}

# Transiciones permitidas; solo un humano puede confirmar/publicar.
_TRANSITIONS: dict[PlaceholderStatus, frozenset[PlaceholderStatus]] = {
    PlaceholderStatus.DETECTED: frozenset({PlaceholderStatus.PENDING_REVIEW}),
    PlaceholderStatus.PENDING_REVIEW: frozenset(
        {PlaceholderStatus.CONFIRMED, PlaceholderStatus.DISCARDED}
    ),
    PlaceholderStatus.CONFIRMED: frozenset(),
    PlaceholderStatus.DISCARDED: frozenset(),
}

_AI_ACTOR_MARKERS = ("ai-", "ai_", "bot", "ollama", "model", "llm", "auto")


def normalize_key(raw: str, *, fallback: str = "") -> str:
    """Normaliza una etiqueta a clave snake_case determinista.

    - Aplica NFKD y filtra a ASCII para estabilidad.
    - Minúsculas, separadores no alfanuméricos a "_".
    - Devuelve ``fallback`` cuando no queda una clave válida.
    """
    text = unicodedata.normalize("NFKD", raw.strip())
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", ascii_text.lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)[:64].strip("_")
    if _KEY_RE.fullmatch(slug):
        return slug
    candidate = fallback.strip()
    if _KEY_RE.fullmatch(candidate):
        return candidate
    return ""


def is_valid_key(value: str) -> bool:
    """Indica si una clave ya normalizada es válida."""
    return _KEY_RE.fullmatch(value) is not None


def is_plausible_raw_key(value: str) -> bool:
    """Indica si el texto interno de un marcador es un identificador plausible."""
    stripped = value.strip()
    if not stripped or len(stripped) > 80:
        return False
    return _VALID_KEY_CHARS_RE.fullmatch(stripped) is not None


def confidence_for(syntax: PlaceholderSyntax) -> float:
    """Confianza determinista por sintaxis."""
    return _CONFIDENCE[syntax]


def explanation_for(syntax: PlaceholderSyntax) -> str:
    """Explicación determinista sin contenido ni PII."""
    return _EXPLANATIONS[syntax]


def infer_field_kind(normalized_key: str, syntax: PlaceholderSyntax) -> FieldKind:
    """Infiere tipo/formato desde la clave o el control nativo."""
    key = normalized_key.lower()
    if syntax == PlaceholderSyntax.NATIVE_FORMFIELD and (
        "check" in key or key in {"si_no", "acepto", "checkbox"}
    ):
        return FieldKind.CHECKBOX
    if any(token in key for token in ("fecha", "date", "dia", "ano", "year")):
        return FieldKind.DATE
    if any(
        token in key for token in ("monto", "importe", "precio", "saldo", "currency")
    ):
        return FieldKind.CURRENCY
    if any(
        token in key
        for token in (
            "numero",
            "number",
            "expediente",
            "dni",
            "cuil",
            "cuit",
            "telefono",
            "folio",
            "articulo",
        )
    ):
        return FieldKind.NUMBER
    if "email" in key or "correo" in key or "mail" in key:
        return FieldKind.EMAIL
    if any(token in key for token in ("check", "acepta", "conforme", "tilda")):
        return FieldKind.CHECKBOX
    return FieldKind.TEXT


def validate_human_actor(actor: str) -> str:
    """Valida que el actor sea humano; rechaza marcadores de IA/automatismo."""
    cleaned = " ".join(actor.split())
    if not cleaned or len(cleaned) > 200:
        raise ValueError("PLACEHOLDER_ACTOR_INVALID")
    lowered = cleaned.lower()
    if any(marker in lowered for marker in _AI_ACTOR_MARKERS):
        raise ValueError("PLACEHOLDER_AI_CONFIRM_FORBIDDEN")
    return cleaned


@dataclass(frozen=True, slots=True)
class PlaceholderLocation:
    """Ubicación estructural determinista de una ocurrencia."""

    origin: PlaceholderOrigin
    order: int
    paragraph_index: int | None = None
    table_index: int | None = None
    table_row: int | None = None
    table_col: int | None = None
    section_index: int = 0

    def __post_init__(self) -> None:
        if self.order < 0:
            raise ValueError("PLACEHOLDER_LOCATION_INVALID")
        if self.section_index < 0:
            raise ValueError("PLACEHOLDER_LOCATION_INVALID")
        if self.origin == PlaceholderOrigin.TABLE_CELL:
            if self.table_index is None or self.table_row is None:
                raise ValueError("PLACEHOLDER_LOCATION_INVALID")
            if self.table_col is None:
                raise ValueError("PLACEHOLDER_LOCATION_INVALID")
            if self.table_index < 0 or self.table_row < 0 or self.table_col < 0:
                raise ValueError("PLACEHOLDER_LOCATION_INVALID")
        if self.paragraph_index is not None and self.paragraph_index < 0:
            raise ValueError("PLACEHOLDER_LOCATION_INVALID")

    def to_safe_dict(self) -> dict[str, object]:
        """Representación auditable sin contenido."""
        return {
            "origin": self.origin.value,
            "order": self.order,
            "paragraph_index": self.paragraph_index,
            "table_index": self.table_index,
            "table_row": self.table_row,
            "table_col": self.table_col,
            "section_index": self.section_index,
        }


@dataclass(slots=True)
class PlaceholderCandidate:
    """Candidato agrupado por clave normalizada con todas sus ubicaciones."""

    original_text: str = field(repr=False)
    normalized_key: str
    origin: PlaceholderOrigin
    syntax: PlaceholderSyntax
    confidence: float
    explanation: str
    status: PlaceholderStatus = PlaceholderStatus.DETECTED
    field_kind: FieldKind = FieldKind.TEXT
    occurrences: int = 1
    locations: tuple[PlaceholderLocation, ...] = ()

    def __post_init__(self) -> None:
        if not self.original_text.strip() or len(self.original_text) > 500:
            raise ValueError("PLACEHOLDER_ORIGINAL_INVALID")
        if not is_valid_key(self.normalized_key):
            raise ValueError("PLACEHOLDER_KEY_INVALID")
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError("PLACEHOLDER_CONFIDENCE_INVALID")
        if not self.explanation.strip() or len(self.explanation) > 500:
            raise ValueError("PLACEHOLDER_EXPLANATION_INVALID")
        if self.occurrences <= 0:
            raise ValueError("PLACEHOLDER_OCCURRENCES_INVALID")
        if self.locations and len(self.locations) != self.occurrences:
            raise ValueError("PLACEHOLDER_OCCURRENCES_INVALID")

    def request_review(self) -> None:
        """Mueve DETECTED a PENDING_REVIEW sin IA."""
        if self.status is not PlaceholderStatus.DETECTED:
            raise ValueError("PLACEHOLDER_TRANSITION_INVALID")
        self.status = PlaceholderStatus.PENDING_REVIEW

    def resolve(self, *, confirmed: bool, actor: str) -> None:
        """Confirma o descarta solo con actor humano explícito."""
        human = validate_human_actor(actor)
        if not human:
            raise ValueError("PLACEHOLDER_ACTOR_INVALID")
        if self.status is not PlaceholderStatus.PENDING_REVIEW:
            raise ValueError("PLACEHOLDER_TRANSITION_INVALID")
        self.status = (
            PlaceholderStatus.CONFIRMED if confirmed else PlaceholderStatus.DISCARDED
        )

    def to_safe_dict(self) -> dict[str, object]:
        """Representación auditable sin texto original ni PII."""
        return {
            "normalized_key": self.normalized_key,
            "origin": self.origin.value,
            "syntax": self.syntax.value,
            "confidence": self.confidence,
            "status": self.status.value,
            "field_kind": self.field_kind.value,
            "occurrences": self.occurrences,
            "locations": [loc.to_safe_dict() for loc in self.locations],
        }
