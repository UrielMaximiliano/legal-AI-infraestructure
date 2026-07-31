"""002 employees and case files

Revision ID: 002
Revises: 001
Create Date: 2026-07-31
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create employees table
    op.create_table(
        "employees",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("employee_number", sa.String(50), nullable=False, unique=True),
        sa.Column("first_name", sa.String(200), nullable=False),
        sa.Column("last_name", sa.String(200), nullable=False),
        sa.Column("document_type", sa.String(20), nullable=False),
        sa.Column("document_number", sa.String(100), nullable=False),
        sa.Column("cuil", sa.String(11), nullable=True, unique=True),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("position", sa.String(200), nullable=True),
        sa.Column("department", sa.String(200), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # Create indexes for employees
    op.create_index(
        "ix_employees_employee_number", "employees", ["employee_number"], unique=True
    )
    op.create_index(
        "ix_employees_document",
        "employees",
        ["document_type", "document_number"],
        unique=True,
    )
    op.create_index(
        "ix_employees_cuil",
        "employees",
        ["cuil"],
        unique=True,
        postgresql_where=sa.text("cuil IS NOT NULL"),
    )
    op.create_index("ix_employees_active", "employees", ["active"])
    op.create_index("ix_employees_department", "employees", ["department"])
    op.create_index("ix_employees_created_at", "employees", ["created_at"])

    # Create case_files table
    op.create_table(
        "case_files",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("case_number", sa.String(50), nullable=False, unique=True),
        sa.Column(
            "employee_id",
            UUID(as_uuid=True),
            sa.ForeignKey("employees.id"),
            nullable=False,
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("case_type", sa.String(50), nullable=False),
        sa.Column(
            "status", sa.String(30), nullable=False, server_default=sa.text("'draft'")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Create indexes for case_files
    op.create_index(
        "ix_case_files_case_number", "case_files", ["case_number"], unique=True
    )
    op.create_index("ix_case_files_employee_id", "case_files", ["employee_id"])
    op.create_index("ix_case_files_status", "case_files", ["status"])
    op.create_index("ix_case_files_case_type", "case_files", ["case_type"])
    op.create_index("ix_case_files_opened_at", "case_files", ["opened_at"])
    op.create_index("ix_case_files_created_at", "case_files", ["created_at"])

    # Create case_status_history table
    op.create_table(
        "case_status_history",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "case_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("case_files.id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(30), nullable=True),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column(
            "changed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("changed_by", sa.String(200), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("request_id", sa.String(128), nullable=True),
    )

    # Create indexes for case_status_history
    op.create_index("ix_history_case_file_id", "case_status_history", ["case_file_id"])
    op.create_index("ix_history_changed_at", "case_status_history", ["changed_at"])


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table("case_status_history")
    op.drop_table("case_files")
    op.drop_table("employees")
