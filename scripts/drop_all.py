import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.db import engine
from core.models import Base

# This will drop all tables defined in models.py
# If there are old tables not in models.py, they won't be dropped cleanly,
# so we can just drop the schema and recreate it.
from sqlalchemy import text

def reset_db():
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE;"))
        conn.execute(text("CREATE SCHEMA public;"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public;"))
        conn.commit()
    print("Database schema dropped and recreated.")

if __name__ == "__main__":
    reset_db()
