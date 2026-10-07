from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config import settings

# If using sqlite, add check_same_thread=False
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from app import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # Safe auto-migration for existing tables
    with engine.connect() as conn:
        for sql in [
            "ALTER TABLE executions ADD COLUMN run_number INTEGER DEFAULT 1",
            "ALTER TABLE executions ADD COLUMN healing_status VARCHAR(32) DEFAULT 'none'",
            "ALTER TABLE executions ADD COLUMN healing_attempts_count INTEGER DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN wire_traces_count INTEGER DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN cloudtrail_matched_count INTEGER DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN orphan_detected BOOLEAN DEFAULT 0",
            "ALTER TABLE executions ADD COLUMN three_leg_status VARCHAR(32) DEFAULT 'pending'",
            "ALTER TABLE executions ADD COLUMN created_resources_json TEXT",
            "ALTER TABLE plans ADD COLUMN connection_id VARCHAR(64)",
            "ALTER TABLE plans ADD COLUMN execution_policy_json TEXT",
            "ALTER TABLE connections ADD COLUMN execution_policy_json TEXT",
            "ALTER TABLE sessions ADD COLUMN requirements_md TEXT",
            "DROP INDEX IF EXISTS ix_connections_name",
            "UPDATE connections SET name = name || '__deleted_' || substr(id, 6, 8) || '_' || strftime('%s', 'now') WHERE is_deleted = 1 AND name NOT LIKE '%__deleted_%'",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_connections_name_active ON connections (name) WHERE is_deleted = 0",
        ]:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass

