from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from app.schemas.database import DatabaseSchema


class DatabaseAdapter(ABC):
    """Abstract base for database DDL, commands, and execution adapters."""

    @abstractmethod
    def get_provider_name(self) -> str:
        """e.g. 'postgresql', 'mysql', 'mongodb'"""
        pass

    @abstractmethod
    def generate_ddl(self, db_schema: DatabaseSchema) -> str:
        """Generate SQL DDL or NoSQL commands representation from the database schema."""
        pass

    @abstractmethod
    def execute_ddl(self, ddl: str, connection_string: str) -> bool:
        """Execute DDL statements or script against target database."""
        pass

    def execute_schema(self, db_schema: DatabaseSchema, connection_string: str) -> bool:
        """Execute schema creation directly against target database."""
        ddl = self.generate_ddl(db_schema)
        return self.execute_ddl(ddl, connection_string)


def get_database_adapter(provider: str) -> DatabaseAdapter:
    """Factory to retrieve database adapter for a given provider."""
    provider_clean = (provider or "postgresql").lower().strip()
    if provider_clean == "postgresql":
        from app.adapters.database.postgresql import PostgreSQLAdapter
        return PostgreSQLAdapter()
    elif provider_clean == "mysql":
        from app.adapters.database.mysql import MySQLAdapter
        return MySQLAdapter()
    elif provider_clean == "mongodb":
        from app.adapters.database.mongodb import MongoDBAdapter
        return MongoDBAdapter()
    else:
        # Default fallback
        from app.adapters.database.postgresql import PostgreSQLAdapter
        return PostgreSQLAdapter()

