import os
from pathlib import Path

from sqlalchemy import URL, create_engine, make_url, text
from sqlalchemy.orm import sessionmaker

from app.environment import load_environment

load_environment()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

# An explicit URL allows isolated test databases. Otherwise build a URL safely
# so reserved characters in credentials are escaped by SQLAlchemy.
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    connect_url = DATABASE_URL
else:
    connect_url = URL.create(
        "mysql+pymysql",
        username=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=int(DB_PORT) if DB_PORT else None,
        database=DB_NAME,
    )

connect_args = {}
ca_certificate = os.getenv("DB_SSL_CA_CERT")
configured_host = make_url(connect_url).host if DATABASE_URL else DB_HOST
is_aiven = bool(configured_host and configured_host.endswith(".aivencloud.com"))
if ca_certificate:
    ca_path = Path(ca_certificate)
    if not ca_path.is_file():
        raise RuntimeError("DB_SSL_CA_CERT does not point to a readable CA certificate file")
    connect_args["ssl"] = {
        "ca": str(ca_path),
        "check_hostname": True,
        "verify_mode": "required",
    }
elif is_aiven:
    raise RuntimeError("Aiven MySQL requires DB_SSL_CA_CERT for verified TLS")

engine = create_engine(connect_url, pool_pre_ping=True, connect_args=connect_args)

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
        # DB driver exceptions can include hosts, usernames, or connection URLs.
        print("Error type:", type(e).__name__)

        return False
