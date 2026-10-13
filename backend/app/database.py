import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.environment import load_environment

load_environment()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# MySQL connection URL. An explicit URL allows isolated test databases without
# changing the application's .env configuration.
DATABASE_URL = os.getenv("DATABASE_URL") or (
    f"mysql+pymysql://{DB_USER}:{DB_PASSWORD}"
    f"@{DB_HOST}:{DB_PORT}/{DB_NAME}"
)

# Create SQLAlchemy engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True
)

# Create session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


# Database dependency for future API routes
def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()


# Test MySQL connection
def test_connection():
    try:
        with engine.connect() as connection:
            result = connection.execute(text("SELECT 1"))

            print("✅ MySQL connection successful!")
            print("Result:", result.scalar())

            return True

    except Exception as e:
        print("❌ MySQL connection failed!")
        print("Error:", e)

        return False