from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    project_name: str = "Stratum"

    # Database Settings matching .env
    db_name: str = "stratum"
    db_user: str = "postgres"
    db_password: str = "postgres"
    db_host: str = "localhost"
    db_port: str = "5432"
    
    @property
    def database_url(self) -> str:
        return f"postgresql://{self.db_user}:{self.db_password}@{self.db_host}:{self.db_port}/{self.db_name}"

    # Model Settings
    embedding_model: str = "nomic-embed-text"
    embedding_dimension: int = 768  # Adjust based on the actual model
    
    # LLM Provider
    default_llm_provider: str = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    default_generation_model: str = "llama3.2:latest"

    # Retrieval tuning
    # Cross-encoder (ms-marco-MiniLM) logits range roughly -11 (irrelevant) to +11
    # (highly relevant). Many genuinely relevant passages still score negative, so the
    # refusal threshold must be conservative or the bot refuses normal questions.
    refusal_score_threshold: float = -9.5

    # Branding / fallback contact used in prompts and fallback messages
    support_email: str = "support@example.com"

    # API key the embeddable chat widget sends as a Bearer token. Injected into
    # chatbot.js at serve time (see app/main.py) so it isn't hardcoded in the JS.
    chatbot_api_key: str = ""

    # The "global" knowledge base. Documents under this project are stored with
    # company scope, so they are available to EVERY project's chatbot (e.g. a user
    # on any project's bot can still ask about leave / holiday / HR policy).
    global_project_slug: str = "general-policy"

    # ----------------------------------------------------------------------- #
    # Admin authentication
    # ----------------------------------------------------------------------- #
    # Secret used to sign admin session tokens. MUST be overridden in .env for
    # production (SECRET_KEY=...). If left blank a random key is generated at
    # startup, which invalidates existing tokens on every restart.
    secret_key: str = ""

    # How long an admin login stays valid (seconds). Default: 12 hours.
    session_ttl_seconds: int = 12 * 60 * 60

    # Default admin account seeded on first startup if no users exist. Change the
    # password immediately after first login (or set these in .env).
    admin_default_username: str = "admin"
    admin_default_password: str = "ChangeMe!123"
    admin_default_full_name: str = "Administrator"

    # ----------------------------------------------------------------------- #
    # Document vision / OCR  (routing rationale: ocrplan.md)
    # ----------------------------------------------------------------------- #
    # Ollama vision model used to deep-scan rich pages (tables, charts, scanned
    # pages). Pull it with `ollama pull glm-ocr`. If it isn't available the
    # pipeline degrades to Tesseract, then to the plain PDF text layer.
    ocr_model: str = "glm-ocr:latest"
    # Render resolution for pages sent to the vision model. 150 dpi resolves
    # 10pt text at ~4x less pixel cost than 300 dpi.
    ocr_page_dpi: int = 150
    # Per-page ceiling for a vision call; on timeout the page keeps its text layer.
    ocr_timeout_seconds: int = 120

    # ----------------------------------------------------------------------- #
    # Document upload limits
    # ----------------------------------------------------------------------- #
    max_upload_mb: int = 25
    allowed_upload_extensions: str = "pdf,doc,docx,txt"

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def allowed_extensions_set(self) -> set:
        return {
            "." + e.strip().lower().lstrip(".")
            for e in self.allowed_upload_extensions.split(",")
            if e.strip()
        }

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()

# Ensure a signing key always exists. A blank SECRET_KEY means tokens are signed
# with a per-process random key: logins survive within a run but are invalidated
# on restart. Set SECRET_KEY in .env to keep sessions stable across restarts.
if not settings.secret_key:
    import secrets as _secrets
    settings.secret_key = _secrets.token_hex(32)
