from app.db import SessionLocal
from sqlalchemy import text

try:
    db = SessionLocal()
    db.execute(text("SELECT 1"))
    print("✅ DB connection successful")
except Exception as e:
    print("❌ DB connection error:\n", e)
