import os
import sys
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Isolate all tests from production backend/vellum.db
TEST_DB_PATH = "/tmp/vellum_pytest_isolated.db"
test_db_url = f"sqlite:///{TEST_DB_PATH}"

# Ensure fresh test database per test run
if os.path.exists(TEST_DB_PATH):
    try:
        os.remove(TEST_DB_PATH)
    except Exception:
        pass

import app.config as app_config
import app.database as app_db

app_config.settings.DATABASE_URL = test_db_url

test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False, "timeout": 30})
test_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

app_db.engine = test_engine
app_db.SessionLocal = test_SessionLocal


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure database schema is created and initialized before tests run on the isolated test db."""
    from app.models import Base
    Base.metadata.create_all(bind=test_engine)
    app_db.init_db()
    yield
    # Cleanup after test session
    try:
        test_engine.dispose()
        if os.path.exists(TEST_DB_PATH):
            os.remove(TEST_DB_PATH)
    except Exception:
        pass


@pytest.fixture
def db_session():
    """Yield a database session bound to the isolated test database."""
    db = test_SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def clean_database_connections():
    """Ensure connections table is cleared after each test to prevent cross-test state leakage."""
    yield
    db = test_SessionLocal()
    try:
        from app.models import ConnectionRecord
        db.query(ConnectionRecord).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()

