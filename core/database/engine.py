from sqlmodel import create_engine, SQLModel, Session
from .models import User, Education, Experience, PlatformCredential, JobApplication
import os

DB_FILE = "intern_bot.db"

# Initial placeholder engine
engine = None

def init_engine(db_key: str = None):
    """Initializes the SQLAlchemy engine, optionally with a SQLCipher key."""
    global engine
    if db_key:
        # Requires pysqlcipher3 to be installed
        try:
            import pysqlcipher3
            sqlite_url = f"sqlite+pysqlcipher://:{db_key}@/{DB_FILE}"
            print("Using SQLCipher encryption.")
        except ImportError:
            print("WARNING: pysqlcipher3 not found. Falling back to unencrypted SQLite.")
            sqlite_url = f"sqlite:///{DB_FILE}"
    else:
        sqlite_url = f"sqlite:///{DB_FILE}"

    connect_args = {"check_same_thread": False}
    engine = create_engine(sqlite_url, echo=False, connect_args=connect_args)
    return engine

def create_db_and_tables():
    """Create the database tables based on the SQLModel definitions."""
    if engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    SQLModel.metadata.create_all(engine)

def get_session() -> Session:
    """Return a database session."""
    if engine is None:
        raise RuntimeError("Database engine not initialized. Call init_engine() first.")
    return Session(engine)
