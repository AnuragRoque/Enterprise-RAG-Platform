import enum
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Boolean, Enum, JSON, ARRAY, Float
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import TSVECTOR

Base = declarative_base()

class ScopeEnum(str, enum.Enum):
    project = "project"
    company = "company"

class DocTypeEnum(str, enum.Enum):
    faq = "faq"
    policy = "policy"
    documentation = "documentation"
    flow = "flow"
    rules = "rules"

class StatusEnum(str, enum.Enum):
    active = "active"
    draft = "draft"
    inactive = "inactive"

class JobStateEnum(str, enum.Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"

class AdminUser(Base):
    """A user allowed to log into the admin panel."""
    __tablename__ = 'admin_users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    full_name = Column(String)
    is_active = Column(Boolean, default=True, nullable=False)
    is_superuser = Column(Boolean, default=False, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Project(Base):
    __tablename__ = 'projects'

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, nullable=False)
    description = Column(String)
    # 'active' | 'disabled' — a disabled project's chat endpoint returns 403.
    status = Column(String, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    api_keys = relationship("ApiKey", back_populates="project")
    documents = relationship("Document", back_populates="project")
    conversations = relationship("Conversation", back_populates="project")


class ApiKey(Base):
    __tablename__ = 'api_keys'

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    key_hash = Column(String, unique=True, nullable=False)
    label = Column(String)
    scopes = Column(JSON, default=list) # Array of scopes
    rate_limit_per_min = Column(Integer, default=60)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    project = relationship("Project", back_populates="api_keys")


class Document(Base):
    __tablename__ = 'documents'

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    scope = Column(Enum(ScopeEnum), nullable=False)
    doc_type = Column(Enum(DocTypeEnum), nullable=False)
    title = Column(String, nullable=False)
    description = Column(String)
    source_path = Column(String)
    checksum = Column(String) # sha256
    version = Column(Integer, default=1)
    status = Column(Enum(StatusEnum), default=StatusEnum.draft)
    valid_from = Column(DateTime(timezone=True), nullable=True)
    page_count = Column(Integer, default=0)
    lang = Column(String, default="en")
    created_by = Column(String)
    updated_by = Column(String)

    # ---- Document-vision / OCR routing (see ocrplan.md) ----
    # What the uploader claimed: 'auto' | 'rich' | 'plain'
    content_hint = Column(String, default="auto")
    # What the pipeline decided: 'standard' | 'deep'
    processing_mode = Column(String, default="standard")
    # Engine(s) that actually ran: 'pymupdf' | 'glm-ocr' | 'tesseract' | 'mixed'
    ocr_engine = Column(String, nullable=True)
    # Pre-scan detection summary: {tables, images, charts, scanned_pages, rich_pages: [...]}
    rich_content = Column(JSON, nullable=True)
    # True = uploader said 'plain' but the pre-scan found rich content; ingestion is
    # parked until the admin confirms a processing mode in the panel.
    needs_review = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    project = relationship("Project", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = 'document_chunks'

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    
    # Denormalized fields for faster filtering
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    scope = Column(Enum(ScopeEnum), nullable=False)
    doc_type = Column(Enum(DocTypeEnum), nullable=False)
    
    chunk_index = Column(Integer, nullable=False)
    text = Column(String, nullable=False) # Full chunk text
    page = Column(Integer)
    section = Column(String)
    token_count = Column(Integer)
    
    # Needs config for dimensions, default to 768 for nomic-embed-text
    embedding = Column(ARRAY(Float), nullable=True) 
    tsv = Column(TSVECTOR) # Postgres FTS
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    document = relationship("Document", back_populates="chunks")


class Conversation(Base):
    __tablename__ = 'conversations'

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    external_user_id = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_active = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    project = relationship("Project", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation")


class Message(Base):
    __tablename__ = 'messages'

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey('conversations.id'), nullable=False)
    role = Column(String, nullable=False) # 'user', 'assistant', 'system'
    content = Column(String, nullable=False)
    citations = Column(JSON) # Store citations JSON metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    conversation = relationship("Conversation", back_populates="messages")


class IngestJob(Base):
    __tablename__ = 'ingest_jobs'

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey('documents.id'), nullable=False)
    state = Column(Enum(JobStateEnum), default=JobStateEnum.queued)
    attempts = Column(Integer, default=0)
    error = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class QueryLog(Base):
    __tablename__ = 'query_logs'

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=False)
    query = Column(String, nullable=False)
    lang = Column(String)
    retrieved_ids = Column(JSON) # Array of chunk IDs
    top_score = Column(Integer) # or Float depending on scoring
    grounded = Column(Boolean)
    latency_ms = Column(Integer)
    blocked_reason = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String)
    action = Column(String)
    target = Column(String)
    meta_data = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AppSetting(Base):
    """Key/value store for global platform toggles managed from the admin panel.

    Known keys (all JSON values):
      global_project_enabled  bool — merge the shared knowledge base into every project
      cross_project_linking   bool — let every project search all projects' chunks
      domain_whitelist_enforced bool — reject browser calls from non-whitelisted origins
    """
    __tablename__ = 'app_settings'

    key = Column(String, primary_key=True)
    value = Column(JSON, nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ApiRequestLog(Base):
    """One row per chat-API request — feeds the admin API Monitor dashboard."""
    __tablename__ = 'api_request_logs'

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    # Denormalized so history survives project deletion/rename.
    project_slug = Column(String, index=True)
    path = Column(String)
    method = Column(String, default="POST")
    # Origin of the calling site (scheme://host from Origin/Referer), or 'direct'
    # for server-to-server calls with no browser origin.
    origin = Column(String, index=True)
    client_ip = Column(String)
    user_agent = Column(String)
    status_code = Column(Integer)
    latency_ms = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AllowedDomain(Base):
    """Domain whitelist for the chat API. project_id NULL = applies to all projects."""
    __tablename__ = 'allowed_domains'

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey('projects.id'), nullable=True)
    # Hostname only, lowercase, no scheme/port — e.g. 'docs.example.com'.
    domain = Column(String, nullable=False, index=True)
    note = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
