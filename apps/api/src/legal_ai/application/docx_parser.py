"""Parser DOCX read-only para detección determinista de placeholders.

Cubre párrafos, tablas, encabezados y pies; tolera runs partidos porque
opera sobre el texto concatenado de cada contenedor. Detecta
``{{campo}}``, ``{campo}``, ``[campo]``, ``<<campo>>``, ``[COMPLETAR]``,
blancos con guiones, elipsis y controles nativos soportados por
python-docx/lxml (w:sdt, MERGEFIELD, FORMTEXT/FORMCHECKBOX).

Seguridad: valida extensión/MIME, rechaza DOCM/macros, valida ZIP
(entradas, tamaño, ratio, path traversal), rechaza relaciones externas no
hipervínculo y XML con DOCTYPE/ENTITY, limita tamaños y candidatos, nunca
modifica el original y nunca registra contenido/PII. No usa IA.
"""

from __future__ import annotations

import hashlib
import re
import time
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from docx import Document
from docx.document import Document as DocumentObject
from docx.table import Table

from legal_ai.config import settings
from legal_ai.domain.docx_placeholders import (
    FieldKind,
    PlaceholderCandidate,
    PlaceholderLocation,
    PlaceholderOrigin,
    PlaceholderStatus,
    PlaceholderSyntax,
    confidence_for,
    explanation_for,
    infer_field_kind,
    is_plausible_raw_key,
    normalize_key,
)
from legal_ai.observability.logging import log_event

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

_MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
_MAX_ENTRIES = 500
_MAX_COMPRESSION_RATIO = 100
_MAX_CANDIDATES = 1000
_MAX_TEXT_BYTES = 2 * 1024 * 1024

_MACRO_NAME_MARKERS = (
    "vbaproject",
    "vbadata",
    "macros",
    "oleobject",
    "activex",
    "word/macros",
)
_REL_EXTERNAL_RE = re.compile(
    r"<Relationship\b[^>]*TargetMode\s*=\s*\"External\"[^>]*>", re.IGNORECASE
)
_REL_TYPE_RE = re.compile(r"Type\s*=\s*\"([^\"]+)\"", re.IGNORECASE)

_DOUBLE_BRACE_RE = re.compile(
    r"\{\{\s*([^\{\}\n]{1,80})\s*\}\}",
)
_DOUBLE_ANGLE_RE = re.compile(r"<<\s*([^<>\n]{1,80})\s*>>")
_SINGLE_BRACE_RE = re.compile(r"(?<!\{)\{\s*([^\{\}\n]{1,80})\s*\}(?!\})")
_BRACKET_RE = re.compile(r"\[([^\[\]\n]{1,80})\]")
_COMPLETAR_RE = re.compile(r"\[\s*COMPLETAR[^\]\n]{0,60}\]", re.IGNORECASE)
_DATE_BLANK_RE = re.compile(r"_{2,}\s*[/\-.]\s*_{2,}(?:\s*[/\-.]\s*_{2,})+")
_BLANK_RE = re.compile(r"_{3,}")
_ELLIPSIS_RE = re.compile(r"\.{3,}|…")
_LABEL_PREFIX_RE = re.compile(
    r"([A-Za-zÁÉÍÓÚÜÑáéíóúüñ]"
    r"[A-Za-z0-9ÁÉÍÓÚÜÑáéíóúüñ _.\-]{0,60})"
    r"\s*:\s*[$€£¥\s]*$"
)
_MERGEFIELD_RE = re.compile(r"MERGEFIELD\s+([A-Za-z_][A-Za-z0-9_.\-]*)", re.IGNORECASE)
_FORMFIELD_RE = re.compile(r"FORM(TEXT|CHECKBOX|DROPDOWN)\b", re.IGNORECASE)

_WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_NS = {"w": _WORD_NS}


class DocxParseError(ValueError):
    """Error sanitizado del parser; nunca incluye contenido ni rutas."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class DocxParserConfig:
    """Límites operativos del parser."""

    max_file_bytes: int = 20 * 1024 * 1024
    max_uncompressed_bytes: int = _MAX_UNCOMPRESSED_BYTES
    max_entries: int = _MAX_ENTRIES
    max_compression_ratio: int = _MAX_COMPRESSION_RATIO
    max_candidates: int = _MAX_CANDIDATES
    max_text_bytes: int = _MAX_TEXT_BYTES


@dataclass(frozen=True, slots=True)
class DocxParseResult:
    """Resultado inmutable del parseo; no expone PII en su vista segura."""

    candidates: tuple[PlaceholderCandidate, ...]
    document_sha256: str
    size_bytes: int
    text_bytes: int

    def to_safe_dict(self) -> dict[str, object]:
        return {
            "candidates": len(self.candidates),
            "occurrences": sum(c.occurrences for c in self.candidates),
            "size_bytes": self.size_bytes,
            "text_bytes": self.text_bytes,
            "sha256": self.document_sha256,
        }


@dataclass(slots=True)
class _RawHit:
    original_text: str
    raw_key: str
    syntax: PlaceholderSyntax
    origin: PlaceholderOrigin
    order: int
    paragraph_index: int | None
    table_index: int | None
    table_row: int | None
    table_col: int | None
    section_index: int
    confidence_override: float | None = None


class DocxParser:
    """Servicio puro de parseo; no persiste, no modifica, no usa IA."""

    def __init__(self, config: DocxParserConfig | None = None) -> None:
        self._config = config or DocxParserConfig(
            max_file_bytes=settings.export.max_docx_size_bytes,
        )

    def parse_path(
        self, path: Path, *, declared_mime: str | None = None
    ) -> DocxParseResult:
        """Parsea un .docx desde disco sin modificarlo."""
        started = time.perf_counter()
        try:
            self._validate_extension(path.name)
            self._validate_mime(declared_mime)
            size = self._validate_size(path)
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise DocxParseError("DOCX_READ_FAILED") from exc
            if len(data) != size:
                raise DocxParseError("DOCX_SIZE_MISMATCH")
            result = self._parse_bytes(data, filename=path.name)
            log_event(
                "docx_parse_completed",
                format="docx",
                phase="parse",
                status="success",
                result="success",
                size_bytes=size,
                count=len(result.candidates),
                sha256=result.document_sha256,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            return result
        except DocxParseError as exc:
            log_event(
                "docx_parse_rejected",
                format="docx",
                phase="parse",
                status="rejected",
                result="rejected",
                error_code=exc.code,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise

    def parse_bytes(
        self,
        data: bytes,
        *,
        filename: str,
        declared_mime: str | None = None,
    ) -> DocxParseResult:
        """Parsea bytes en memoria sin tocar el disco original."""
        started = time.perf_counter()
        try:
            self._validate_extension(filename)
            self._validate_mime(declared_mime)
            if not data or len(data) > self._config.max_file_bytes:
                raise DocxParseError("DOCX_SIZE_EXCEEDED")
            result = self._parse_bytes(bytes(data), filename=filename)
            log_event(
                "docx_parse_completed",
                format="docx",
                phase="parse",
                status="success",
                result="success",
                size_bytes=len(data),
                count=len(result.candidates),
                sha256=result.document_sha256,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            return result
        except DocxParseError as exc:
            log_event(
                "docx_parse_rejected",
                format="docx",
                phase="parse",
                status="rejected",
                result="rejected",
                error_code=exc.code,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            raise

    def _parse_bytes(self, data: bytes, *, filename: str) -> DocxParseResult:
        digest = hashlib.sha256(data).hexdigest()
        self._validate_zip(data)
        document = self._load_document(data)
        hits = self._extract_hits(document)
        total_text = sum(len(hit.original_text.encode("utf-8")) for hit in hits)
        if total_text > self._config.max_text_bytes:
            raise DocxParseError("DOCX_TEXT_LIMIT_EXCEEDED")
        candidates = self._group_hits(hits)
        if len(candidates) > self._config.max_candidates:
            raise DocxParseError("DOCX_TOO_MANY_FIELDS")
        return DocxParseResult(
            candidates=candidates,
            document_sha256=digest,
            size_bytes=len(data),
            text_bytes=total_text,
        )

    def _validate_extension(self, filename: str) -> None:
        lowered = filename.lower()
        # Solo .docx; rechaza .docm/.dotm/.dotx/.doc y dobles extensiones.
        if not lowered.endswith(".docx") or lowered.count(".") < 1:
            raise DocxParseError("DOCX_EXTENSION_FORBIDDEN")
        stem = lowered[: -len(".docx")]
        if not stem or stem.endswith((".docm", ".dotm", ".doc", ".dot")):
            raise DocxParseError("DOCX_EXTENSION_FORBIDDEN")
        if lowered.endswith((".docm", ".dotm")):
            raise DocxParseError("DOCX_MACRO_FORBIDDEN")

    @staticmethod
    def _validate_mime(declared_mime: str | None) -> None:
        if declared_mime is not None and declared_mime != DOCX_MIME:
            raise DocxParseError("DOCX_MIME_FORBIDDEN")

    def _validate_size(self, path: Path) -> int:
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise DocxParseError("DOCX_READ_FAILED") from exc
        if size <= 0 or size > self._config.max_file_bytes:
            raise DocxParseError("DOCX_SIZE_EXCEEDED")
        return size

    def _validate_zip(self, data: bytes) -> None:
        try:
            archive = zipfile.ZipFile(BytesIO(data))
            infos = archive.infolist()
        except (zipfile.BadZipFile, RuntimeError, ValueError) as exc:
            raise DocxParseError("DOCX_CORRUPT") from exc
        try:
            if len(infos) == 0 or len(infos) > self._config.max_entries:
                raise DocxParseError("DOCX_LIMIT_EXCEEDED")
            names = {info.filename for info in infos}
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise DocxParseError("DOCX_STRUCTURE_INVALID")
            total_uncompressed = 0
            total_compressed = 0
            for info in infos:
                self._validate_member_name(info.filename)
                total_uncompressed += info.file_size
                total_compressed += info.compress_size
            if total_uncompressed > self._config.max_uncompressed_bytes:
                raise DocxParseError("DOCX_LIMIT_EXCEEDED")
            if total_uncompressed > self._config.max_compression_ratio * max(
                total_compressed, 1
            ):
                raise DocxParseError("DOCX_ZIP_BOMB")
            self._reject_macros(names)
            self._validate_relationships(archive, infos)
            self._validate_xml_safety(archive, infos)
        except DocxParseError:
            raise
        except (OSError, zipfile.BadZipFile, RuntimeError, ValueError) as exc:
            raise DocxParseError("DOCX_CORRUPT") from exc

    @staticmethod
    def _validate_member_name(name: str) -> None:
        path = PurePosixPath(name)
        if path.is_absolute() or any(part in {"..", ""} for part in path.parts):
            raise DocxParseError("DOCX_PATH_TRAVERSAL")
        if name.startswith(("/", "\\")) or ".." in name.split("/"):
            raise DocxParseError("DOCX_PATH_TRAVERSAL")

    def _reject_macros(self, names: set[str]) -> None:
        lowered = {name.lower() for name in names}
        for name in lowered:
            if any(marker in name for marker in _MACRO_NAME_MARKERS):
                raise DocxParseError("DOCX_MACRO_FORBIDDEN")
            # .bin bajo word/ suele ser OLE/macros; los media legítimos
            # viven bajo word/media/ con extensión de imagen/audio.
            if (
                name.endswith((".docm", ".dotm", ".bin"))
                and "word/" in name
                and not name.startswith("word/media/")
            ):
                raise DocxParseError("DOCX_MACRO_FORBIDDEN")

    def _validate_relationships(
        self, archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
    ) -> None:
        for info in infos:
            if not info.filename.endswith(".rels"):
                continue
            try:
                payload = archive.read(info.filename).decode("utf-8", errors="strict")
            except (KeyError, UnicodeDecodeError, RuntimeError) as exc:
                raise DocxParseError("DOCX_CORRUPT") from exc
            for match in _REL_EXTERNAL_RE.finditer(payload):
                tag = match.group(0)
                type_match = _REL_TYPE_RE.search(tag)
                rel_type = type_match.group(1).lower() if type_match else ""
                if "hyperlink" not in rel_type:
                    raise DocxParseError("DOCX_EXTERNAL_REL_FORBIDDEN")

    def _validate_xml_safety(
        self, archive: zipfile.ZipFile, infos: list[zipfile.ZipInfo]
    ) -> None:
        for info in infos:
            if not info.filename.endswith(".xml"):
                continue
            try:
                with archive.open(info.filename) as handle:
                    head = handle.read(4096)
            except (KeyError, RuntimeError, ValueError) as exc:
                raise DocxParseError("DOCX_CORRUPT") from exc
            upper = head.upper()
            if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
                raise DocxParseError("DOCX_XML_FORBIDDEN")

    @staticmethod
    def _load_document(data: bytes) -> DocumentObject:
        try:
            return Document(BytesIO(data))
        except DocxParseError:
            raise
        except Exception as exc:
            raise DocxParseError("DOCX_CORRUPT") from exc

    def _extract_hits(self, document: DocumentObject) -> list[_RawHit]:
        hits: list[_RawHit] = []
        order = 0

        def _collect(
            text: str,
            element: Any,
            *,
            origin: PlaceholderOrigin,
            paragraph_index: int | None,
            table_index: int | None,
            table_row: int | None,
            table_col: int | None,
            section_index: int,
        ) -> None:
            nonlocal order
            # Los controles nativos (MERGEFIELD sin resultado, sdt vacío)
            # pueden no tener texto visible; siempre se inspeccionan.
            native = self._native_hits(
                element,
                origin=origin,
                paragraph_index=paragraph_index,
                table_index=table_index,
                table_row=table_row,
                table_col=table_col,
                section_index=section_index,
                base_order=order,
            )
            hits.extend(native)
            order += len(native)
            if not text:
                return
            textual = self._textual_hits(
                text,
                origin=origin,
                paragraph_index=paragraph_index,
                table_index=table_index,
                table_row=table_row,
                table_col=table_col,
                section_index=section_index,
                base_order=order,
            )
            hits.extend(textual)
            order += len(textual)

        for para_index, paragraph in enumerate(document.paragraphs):
            _collect(
                paragraph.text,
                paragraph._element,
                origin=PlaceholderOrigin.PARAGRAPH,
                paragraph_index=para_index,
                table_index=None,
                table_row=None,
                table_col=None,
                section_index=0,
            )
        for table_index, table in enumerate(document.tables):
            self._collect_table(
                table,
                origin=PlaceholderOrigin.TABLE_CELL,
                table_index=table_index,
                section_index=0,
                collect=_collect,
            )
        for section_index, section in enumerate(document.sections):
            header = section.header
            for para_index, paragraph in enumerate(header.paragraphs):
                _collect(
                    paragraph.text,
                    paragraph._element,
                    origin=PlaceholderOrigin.HEADER,
                    paragraph_index=para_index,
                    table_index=None,
                    table_row=None,
                    table_col=None,
                    section_index=section_index,
                )
            for table_index, table in enumerate(header.tables):
                self._collect_table(
                    table,
                    origin=PlaceholderOrigin.HEADER,
                    table_index=table_index,
                    section_index=section_index,
                    collect=_collect,
                )
            footer = section.footer
            for para_index, paragraph in enumerate(footer.paragraphs):
                _collect(
                    paragraph.text,
                    paragraph._element,
                    origin=PlaceholderOrigin.FOOTER,
                    paragraph_index=para_index,
                    table_index=None,
                    table_row=None,
                    table_col=None,
                    section_index=section_index,
                )
            for table_index, table in enumerate(footer.tables):
                self._collect_table(
                    table,
                    origin=PlaceholderOrigin.FOOTER,
                    table_index=table_index,
                    section_index=section_index,
                    collect=_collect,
                )
        # Controles de bloque (w:sdt hermanos de w:p) no aparecen como
        # descendientes de ningún párrafo; se escanean una vez al final.
        for block_hit in self._block_sdt_hits(document, base_order=order):
            hits.append(block_hit)
            order += 1
        return hits

    def _collect_table(
        self,
        table: Table,
        *,
        origin: PlaceholderOrigin,
        table_index: int,
        section_index: int,
        collect: Any,
    ) -> None:
        for row_index, row in enumerate(table.rows):
            for col_index, cell in enumerate(row.cells):
                for para_index, paragraph in enumerate(cell.paragraphs):
                    collect(
                        paragraph.text,
                        paragraph._element,
                        origin=origin,
                        paragraph_index=para_index,
                        table_index=table_index,
                        table_row=row_index,
                        table_col=col_index,
                        section_index=section_index,
                    )

    def _native_hits(
        self,
        element: Any,
        *,
        origin: PlaceholderOrigin,
        paragraph_index: int | None,
        table_index: int | None,
        table_row: int | None,
        table_col: int | None,
        section_index: int,
        base_order: int,
    ) -> list[_RawHit]:
        found: list[_RawHit] = []
        try:
            sdts = element.findall(".//w:sdt", namespaces=_NS)
        except Exception:
            return found
        offset = 0
        for sdt in sdts:
            alias = self._sdt_attr(sdt, "alias")
            tag = self._sdt_attr(sdt, "tag")
            inner = " ".join(
                t.text or "" for t in sdt.findall(".//w:t", namespaces=_NS)
            ).strip()
            # w:placeholder puede duplicar el texto visible; prioriza alias/tag.
            raw = (alias or tag or inner).strip()
            if not raw:
                continue
            # Evita duplicar un {{campo}} ya visible dentro del mismo sdt.
            if _DOUBLE_BRACE_RE.search(raw) or _DOUBLE_BRACE_RE.search(inner):
                inner_match = _DOUBLE_BRACE_RE.search(inner or raw)
                if inner_match and is_plausible_raw_key(inner_match.group(1)):
                    continue
            syntax = PlaceholderSyntax.NATIVE_SDT
            # sdt de checkbox no trae texto útil; usa alias/tag como clave.
            found.append(
                _RawHit(
                    original_text=f"<sdt>{raw[:120]}</sdt>",
                    raw_key=raw[:80],
                    syntax=syntax,
                    origin=origin,
                    order=base_order + offset,
                    paragraph_index=paragraph_index,
                    table_index=table_index,
                    table_row=table_row,
                    table_col=table_col,
                    section_index=section_index,
                )
            )
            offset += 1
        try:
            instr_nodes = element.findall(".//w:instrText", namespaces=_NS)
            fld_simple = element.findall(".//w:fldSimple", namespaces=_NS)
        except Exception:
            return found
        for node in instr_nodes:
            text = (node.text or "").strip()
            if not text:
                continue
            merge = _MERGEFIELD_RE.search(text)
            if merge:
                found.append(
                    _RawHit(
                        original_text=f"MERGEFIELD {merge.group(1)[:80]}",
                        raw_key=merge.group(1)[:80],
                        syntax=PlaceholderSyntax.NATIVE_MERGEFIELD,
                        origin=origin,
                        order=base_order + offset,
                        paragraph_index=paragraph_index,
                        table_index=table_index,
                        table_row=table_row,
                        table_col=table_col,
                        section_index=section_index,
                    )
                )
                offset += 1
                continue
            form = _FORMFIELD_RE.search(text)
            if form:
                found.append(
                    _RawHit(
                        original_text=f"FORM{form.group(1).upper()}",
                        raw_key=f"form_{form.group(1).lower()}",
                        syntax=PlaceholderSyntax.NATIVE_FORMFIELD,
                        origin=origin,
                        order=base_order + offset,
                        paragraph_index=paragraph_index,
                        table_index=table_index,
                        table_row=table_row,
                        table_col=table_col,
                        section_index=section_index,
                    )
                )
                offset += 1
        for node in fld_simple:
            instr = node.get(f"{{{_WORD_NS}}}instr", "") or ""
            merge = _MERGEFIELD_RE.search(instr)
            if merge:
                found.append(
                    _RawHit(
                        original_text=f"MERGEFIELD {merge.group(1)[:80]}",
                        raw_key=merge.group(1)[:80],
                        syntax=PlaceholderSyntax.NATIVE_MERGEFIELD,
                        origin=origin,
                        order=base_order + offset,
                        paragraph_index=paragraph_index,
                        table_index=table_index,
                        table_row=table_row,
                        table_col=table_col,
                        section_index=section_index,
                    )
                )
                offset += 1
        return found

    def _block_sdt_hits(
        self, document: DocumentObject, *, base_order: int
    ) -> list[_RawHit]:
        """Detecta w:sdt de nivel bloque hermanos de w:p en el cuerpo."""
        found: list[_RawHit] = []
        try:
            body = document.element.body
            blocks = body.findall("w:sdt", namespaces=_NS)
        except Exception:
            return found
        for offset, sdt in enumerate(blocks):
            alias = self._sdt_attr(sdt, "alias")
            tag = self._sdt_attr(sdt, "tag")
            try:
                inner = " ".join(
                    t.text or "" for t in sdt.findall(".//w:t", namespaces=_NS)
                ).strip()
            except Exception:
                inner = ""
            raw = (alias or tag or inner).strip()
            if not raw:
                continue
            if _DOUBLE_BRACE_RE.search(raw) or _DOUBLE_BRACE_RE.search(inner):
                inner_match = _DOUBLE_BRACE_RE.search(inner or raw)
                if inner_match and is_plausible_raw_key(inner_match.group(1)):
                    continue
            found.append(
                _RawHit(
                    original_text=f"<sdt>{raw[:120]}</sdt>",
                    raw_key=raw[:80],
                    syntax=PlaceholderSyntax.NATIVE_SDT,
                    origin=PlaceholderOrigin.PARAGRAPH,
                    order=base_order + offset,
                    paragraph_index=None,
                    table_index=None,
                    table_row=None,
                    table_col=None,
                    section_index=0,
                )
            )
        return found

    @staticmethod
    def _sdt_attr(sdt: Any, name: str) -> str:
        try:
            props = sdt.find("w:sdtPr", namespaces=_NS)
            if props is None:
                return ""
            node = props.find(f"w:{name}", namespaces=_NS)
            if node is None:
                return ""
            return str(node.get(f"{{{_WORD_NS}}}val", "") or "").strip()
        except Exception:
            return ""

    def _textual_hits(
        self,
        text: str,
        *,
        origin: PlaceholderOrigin,
        paragraph_index: int | None,
        table_index: int | None,
        table_row: int | None,
        table_col: int | None,
        section_index: int,
        base_order: int,
    ) -> list[_RawHit]:
        # (start, end, priority, original, raw_key, syntax, confidence_override)
        staged: list[
            tuple[int, int, int, str, str, PlaceholderSyntax, float | None]
        ] = []

        for match in _DOUBLE_BRACE_RE.finditer(text):
            inner = match.group(1)
            if not is_plausible_raw_key(inner):
                continue
            staged.append(
                (
                    match.start(),
                    match.end(),
                    0,
                    match.group(0),
                    inner.strip(),
                    PlaceholderSyntax.DOUBLE_BRACE,
                    None,
                )
            )
        for match in _DOUBLE_ANGLE_RE.finditer(text):
            inner = match.group(1)
            if not is_plausible_raw_key(inner):
                continue
            staged.append(
                (
                    match.start(),
                    match.end(),
                    1,
                    match.group(0),
                    inner.strip(),
                    PlaceholderSyntax.DOUBLE_ANGLE,
                    None,
                )
            )
        for match in _SINGLE_BRACE_RE.finditer(text):
            # Excluye los ya cubiertos por doble llave.
            if text[max(0, match.start() - 1) : match.start() + 1].startswith("{{"):
                continue
            if match.group(0).startswith("{{") or match.group(0).endswith("}}"):
                continue
            inner = match.group(1)
            if not is_plausible_raw_key(inner):
                continue
            staged.append(
                (
                    match.start(),
                    match.end(),
                    2,
                    match.group(0),
                    inner.strip(),
                    PlaceholderSyntax.SINGLE_BRACE,
                    None,
                )
            )
        for match in _COMPLETAR_RE.finditer(text):
            staged.append(
                (
                    match.start(),
                    match.end(),
                    3,
                    match.group(0),
                    self._completar_key(match.group(0)),
                    PlaceholderSyntax.COMPLETAR,
                    None,
                )
            )
        for match in _BRACKET_RE.finditer(text):
            if _COMPLETAR_RE.fullmatch(match.group(0)):
                continue
            inner = match.group(1).strip()
            if not inner:
                continue
            if set(inner) <= {"_", " ", ".", "-", "…"}:
                continue
            staged.append(
                (
                    match.start(),
                    match.end(),
                    4,
                    match.group(0),
                    inner,
                    PlaceholderSyntax.BRACKET,
                    None,
                )
            )
        for match in _DATE_BLANK_RE.finditer(text):
            staged.append(
                (
                    match.start(),
                    match.end(),
                    5,
                    match.group(0),
                    self._label_for(text, match.start()),
                    PlaceholderSyntax.BLANK,
                    0.70,
                )
            )
        for match in _BLANK_RE.finditer(text):
            staged.append(
                (
                    match.start(),
                    match.end(),
                    6,
                    match.group(0),
                    self._label_for(text, match.start()),
                    PlaceholderSyntax.BLANK,
                    None,
                )
            )
        for match in _ELLIPSIS_RE.finditer(text):
            staged.append(
                (
                    match.start(),
                    match.end(),
                    7,
                    match.group(0),
                    self._label_for(text, match.start()),
                    PlaceholderSyntax.ELLIPSIS,
                    None,
                )
            )

        staged.sort(key=lambda item: (item[0], item[2], -(item[1] - item[0])))
        selected: list[
            tuple[int, int, int, str, str, PlaceholderSyntax, float | None]
        ] = []
        last_end = -1
        for item in staged:
            start, end = item[0], item[1]
            if start < last_end:
                continue
            selected.append(item)
            last_end = end

        hits: list[_RawHit] = []
        for index, (_, _, _, original, raw_key, syntax, override) in enumerate(
            selected
        ):
            hits.append(
                _RawHit(
                    original_text=original[:200],
                    raw_key=raw_key[:80],
                    syntax=syntax,
                    origin=origin,
                    order=base_order + index,
                    paragraph_index=paragraph_index,
                    table_index=table_index,
                    table_row=table_row,
                    table_col=table_col,
                    section_index=section_index,
                    confidence_override=override,
                )
            )
        return hits

    @staticmethod
    def _completar_key(fragment: str) -> str:
        inner = fragment.strip()[1:-1].strip()
        # "[COMPLETAR]" -> genérico; "[COMPLETAR: nombre]" -> "nombre".
        remainder = re.sub(r"(?i)^\s*completar\s*[:\-–—]?\s*", "", inner).strip(" _-")
        if remainder and is_plausible_raw_key(remainder):
            return remainder
        if remainder and len(remainder) <= 80:
            return remainder
        return "completar"

    @staticmethod
    def _label_for(text: str, start: int) -> str:
        line_start = text.rfind("\n", 0, start) + 1
        prefix = text[line_start:start]
        match = _LABEL_PREFIX_RE.search(prefix)
        if match:
            return match.group(1).strip()
        return ""

    def _group_hits(self, hits: list[_RawHit]) -> tuple[PlaceholderCandidate, ...]:
        grouped: dict[str, list[_RawHit]] = {}
        fallback_counter = 1

        def _fallback() -> str:
            nonlocal fallback_counter
            while True:
                candidate = f"campo_{fallback_counter}"
                fallback_counter += 1
                if candidate not in grouped:
                    return candidate

        for hit in sorted(hits, key=lambda item: item.order):
            if hit.syntax in {
                PlaceholderSyntax.BLANK,
                PlaceholderSyntax.ELLIPSIS,
                PlaceholderSyntax.COMPLETAR,
                PlaceholderSyntax.NATIVE_SDT,
                PlaceholderSyntax.NATIVE_FORMFIELD,
            }:
                key = normalize_key(
                    hit.raw_key, fallback=_fallback() if not hit.raw_key else ""
                )
                if not key:
                    key = _fallback()
                    # Re-normaliza para garantizar el formato del fallback.
                    key = normalize_key(key, fallback=key) or key
            else:
                key = normalize_key(hit.raw_key, fallback="")
                if not key:
                    # Sintaxis explícita pero clave inválida: usa fallback
                    # estable en lugar de descartar la señal.
                    key = normalize_key(hit.raw_key[:64], fallback=_fallback())
                    if not key:
                        key = _fallback()
            grouped.setdefault(key, []).append(hit)

        candidates: list[PlaceholderCandidate] = []
        for key in sorted(grouped.keys()):
            occurrences = sorted(grouped[key], key=lambda item: item.order)
            first = occurrences[0]
            confidence = (
                first.confidence_override
                if first.confidence_override is not None
                else confidence_for(first.syntax)
            )
            # Blancos sin etiqueta pierden confianza de forma determinista.
            if (
                first.syntax
                in {
                    PlaceholderSyntax.BLANK,
                    PlaceholderSyntax.ELLIPSIS,
                }
                and not first.raw_key.strip()
            ):
                confidence = min(confidence, 0.50)
            field_kind = infer_field_kind(key, first.syntax)
            if first.syntax == PlaceholderSyntax.NATIVE_FORMFIELD:
                text = first.original_text.upper()
                if "CHECKBOX" in text:
                    field_kind = FieldKind.CHECKBOX
            locations = tuple(
                PlaceholderLocation(
                    origin=item.origin,
                    order=item.order,
                    paragraph_index=item.paragraph_index,
                    table_index=item.table_index,
                    table_row=item.table_row,
                    table_col=item.table_col,
                    section_index=item.section_index,
                )
                for item in occurrences
            )
            candidates.append(
                PlaceholderCandidate(
                    original_text=first.original_text,
                    normalized_key=key,
                    origin=first.origin,
                    syntax=first.syntax,
                    confidence=confidence,
                    explanation=explanation_for(first.syntax),
                    status=PlaceholderStatus.DETECTED,
                    field_kind=field_kind,
                    occurrences=len(occurrences),
                    locations=locations,
                )
            )
        return tuple(candidates)
