"""admin console v2 + document-vision OCR fields

- projects: description
- documents: content_hint / processing_mode / ocr_engine / rich_content / needs_review
- new tables: app_settings, api_request_logs, allowed_domains

Revision ID: c7d8e9f0a1b2
Revises: b1a2c3d4e5f6
Create Date: 2026-07-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c7d8e9f0a1b2'
down_revision: Union[str, Sequence[str], None] = 'b1a2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- projects: editable description ----
    op.add_column('projects', sa.Column('description', sa.String(), nullable=True))

    # ---- documents: document-vision / OCR routing fields ----
    op.add_column('documents', sa.Column('content_hint', sa.String(), nullable=True, server_default='auto'))
    op.add_column('documents', sa.Column('processing_mode', sa.String(), nullable=True, server_default='standard'))
    op.add_column('documents', sa.Column('ocr_engine', sa.String(), nullable=True))
    op.add_column('documents', sa.Column('rich_content', sa.JSON(), nullable=True))
    op.add_column('documents', sa.Column('needs_review', sa.Boolean(), nullable=False, server_default=sa.false()))

    # ---- global platform toggles ----
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.JSON(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('key'),
    )

    # ---- API monitor request log ----
    op.create_table(
        'api_request_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('project_slug', sa.String(), nullable=True),
        sa.Column('path', sa.String(), nullable=True),
        sa.Column('method', sa.String(), nullable=True),
        sa.Column('origin', sa.String(), nullable=True),
        sa.Column('client_ip', sa.String(), nullable=True),
        sa.Column('user_agent', sa.String(), nullable=True),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_api_request_logs_id'), 'api_request_logs', ['id'], unique=False)
    op.create_index(op.f('ix_api_request_logs_project_slug'), 'api_request_logs', ['project_slug'], unique=False)
    op.create_index(op.f('ix_api_request_logs_origin'), 'api_request_logs', ['origin'], unique=False)
    op.create_index(op.f('ix_api_request_logs_created_at'), 'api_request_logs', ['created_at'], unique=False)

    # ---- domain whitelist ----
    op.create_table(
        'allowed_domains',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('note', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_allowed_domains_id'), 'allowed_domains', ['id'], unique=False)
    op.create_index(op.f('ix_allowed_domains_domain'), 'allowed_domains', ['domain'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_allowed_domains_domain'), table_name='allowed_domains')
    op.drop_index(op.f('ix_allowed_domains_id'), table_name='allowed_domains')
    op.drop_table('allowed_domains')

    op.drop_index(op.f('ix_api_request_logs_created_at'), table_name='api_request_logs')
    op.drop_index(op.f('ix_api_request_logs_origin'), table_name='api_request_logs')
    op.drop_index(op.f('ix_api_request_logs_project_slug'), table_name='api_request_logs')
    op.drop_index(op.f('ix_api_request_logs_id'), table_name='api_request_logs')
    op.drop_table('api_request_logs')

    op.drop_table('app_settings')

    op.drop_column('documents', 'needs_review')
    op.drop_column('documents', 'rich_content')
    op.drop_column('documents', 'ocr_engine')
    op.drop_column('documents', 'processing_mode')
    op.drop_column('documents', 'content_hint')

    op.drop_column('projects', 'description')
