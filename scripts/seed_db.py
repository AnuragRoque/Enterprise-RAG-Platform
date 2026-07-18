import os
import sys
from sqlalchemy.orm import Session
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import SessionLocal, engine
from core.models import Project, ApiKey, AdminUser, Base
from core.config import settings
from core.security import hash_password

def seed_database():
    # Make sure the admin_users table exists even without running migrations.
    AdminUser.__table__.create(bind=engine, checkfirst=True)

    db: Session = SessionLocal()

    try:
        gp_project = db.query(Project).filter(Project.slug == "general-policy").first()
        if not gp_project:
            print("Seeding general-policy project...")
            gp_project = Project(slug="general-policy", name="General Policy")
            db.add(gp_project)
            db.commit()
            db.refresh(gp_project)

            gp_api_key = ApiKey(project_id=gp_project.id, key_hash="hashed_gp_key", label="default")
            db.add(gp_api_key)

        # Default admin account for the login panel.
        if db.query(AdminUser).count() == 0:
            print(f"Seeding default admin user '{settings.admin_default_username}'...")
            db.add(AdminUser(
                username=settings.admin_default_username,
                password_hash=hash_password(settings.admin_default_password),
                full_name=settings.admin_default_full_name,
                is_active=True,
                is_superuser=True,
            ))

        db.commit()
        print("Database seeded successfully.")
        print(f"  Admin login: {settings.admin_default_username} / {settings.admin_default_password}")

    except Exception as e:
        print(f"Error seeding database: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_database()
