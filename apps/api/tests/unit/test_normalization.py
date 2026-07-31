"""Unit tests for normalization functions."""

import pytest

from legal_ai.domain.normalization import (
    normalize_cuil,
    normalize_document_number,
    normalize_email,
    normalize_phone,
    normalize_text,
)


class TestNormalizeDocumentNumber:
    """Tests for document number normalization."""

    def test_dni_digits_only(self):
        assert normalize_document_number("dni", "30111222") == "30111222"

    def test_dni_with_dots_rejected(self):
        with pytest.raises(ValueError, match="only digits"):
            normalize_document_number("dni", "30.111.222")

    def test_dni_with_letters_rejected(self):
        with pytest.raises(ValueError, match="only digits"):
            normalize_document_number("dni", "30ABC122")

    def test_dni_trim(self):
        assert normalize_document_number("dni", " 30111222 ") == "30111222"

    def test_dni_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_document_number("dni", "")

    def test_lc_alphanumeric_uppercase(self):
        assert normalize_document_number("lc", "abc123") == "ABC123"

    def test_le_alphanumeric_uppercase(self):
        assert normalize_document_number("le", "xyz789") == "XYZ789"

    def test_ci_alphanumeric_uppercase(self):
        assert normalize_document_number("ci", "def456") == "DEF456"

    def test_passport_alphanumeric_uppercase(self):
        assert normalize_document_number("pasaporte", "ab1234") == "AB1234"

    def test_lc_with_special_chars_rejected(self):
        with pytest.raises(ValueError, match="alphanumeric"):
            normalize_document_number("lc", "ABC-123")

    def test_lc_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_document_number("lc", "")


class TestNormalizeCuil:
    """Tests for CUIL normalization."""

    def test_cuil_with_hyphens(self):
        assert normalize_cuil("27-30111222-5") == "27301112225"

    def test_cuil_without_separators(self):
        assert normalize_cuil("27301112225") == "27301112225"

    def test_cuil_with_spaces(self):
        assert normalize_cuil("27 30111222 5") == "27301112225"

    def test_cuil_trim(self):
        assert normalize_cuil(" 27-30111222-5 ") == "27301112225"

    def test_cuil_wrong_length_rejected(self):
        with pytest.raises(ValueError, match="11 digits"):
            normalize_cuil("273011122")

    def test_cuil_letters_rejected(self):
        with pytest.raises(ValueError, match="only digits"):
            normalize_cuil("27-3011122A-5")


class TestNormalizeEmail:
    """Tests for email normalization."""

    def test_email_lowercase(self):
        assert normalize_email("USER@EXAMPLE.COM") == "user@example.com"

    def test_email_trim(self):
        assert normalize_email(" user@example.com ") == "user@example.com"

    def test_email_mixed_case(self):
        assert normalize_email("User@Example.Com") == "user@example.com"


class TestNormalizePhone:
    """Tests for phone normalization."""

    def test_phone_trim(self):
        assert normalize_phone(" +5493794000000 ") == "+5493794000000"

    def test_phone_remove_spaces(self):
        assert normalize_phone("+54 9379 400 0000") == "+5493794000000"


class TestNormalizeText:
    """Tests for text normalization."""

    def test_text_trim(self):
        assert normalize_text("  hello  ") == "hello"

    def test_text_empty_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_text("")

    def test_text_whitespace_only_rejected(self):
        with pytest.raises(ValueError, match="empty"):
            normalize_text("   ")
