from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from app.api import chat, admin, auth
from core.config import settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def ensure_admin_seed() -> None:
    """Idempotently create the admin_users table and a default admin account.

    Runs on startup so the login panel works even before Alembic migrations are
    applied. Safe to run repeatedly: the table is created only if missing and the
    default user is inserted only when no admin users exist.
    """
    from core.db import engine, SessionLocal
    from core.models import AdminUser, Base
    from core.security import hash_password

    # Create just the admin_users table if it isn't there yet (checkfirst=True).
    AdminUser.__table__.create(bind=engine, checkfirst=True)

    db = SessionLocal()
    try:
        if db.query(AdminUser).count() == 0:
            db.add(AdminUser(
                username=settings.admin_default_username,
                password_hash=hash_password(settings.admin_default_password),
                full_name=settings.admin_default_full_name,
                is_active=True,
                is_superuser=True,
            ))
            db.commit()
            print(
                f"[admin] Seeded default admin user '{settings.admin_default_username}'. "
                "Log in and change the password immediately."
            )
    except Exception as e:  # pragma: no cover - startup diagnostics only
        db.rollback()
        print(f"[admin] Could not seed default admin user: {e}")
    finally:
        db.close()

def create_app() -> FastAPI:

    app = FastAPI(title="Stratum API", version="1.0.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Restrict in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(chat.router)
    app.include_router(auth.router)
    app.include_router(admin.router)

    @app.on_event("startup")
    def _startup():
        ensure_admin_seed()

    # Serve the widget script with the API key injected from settings (.env), so the
    # secret isn't baked into the committed JS. Registered before the StaticFiles
    # mount below so this explicit route wins over the raw file.
    @app.get("/static/chatbot.js")
    def serve_chatbot_js():
        js = (STATIC_DIR / "chatbot.js").read_text(encoding="utf-8")
        js = js.replace("__CHATBOT_API_KEY__", settings.chatbot_api_key)
        return Response(content=js, media_type="application/javascript")

    # Mount static files for UI
    app.mount("/static", StaticFiles(directory="static"), name="static")

    from fastapi.responses import FileResponse, RedirectResponse

    @app.get("/")
    def read_root():
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html")

    @app.get("/admin")
    def read_admin():
        return RedirectResponse(url="/static/admin.html")

    @app.get("/health")
    def health_check():
        return {"status": "ok"}

    return app

app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
