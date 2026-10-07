import os
import pytest
from app.schemas.ir import UniversalIR

from app.schemas.database import DatabaseSchema, TableDefinition, ColumnDefinition, CollectionDefinition
from app.adapters.database.mysql import MySQLAdapter
from app.adapters.database.mongodb import MongoDBAdapter
from app.adapters.database.base import get_database_adapter
from app.engines.execution_engine import execution_engine
from app.llm.client import llm_client


def test_mysql_ddl_generation():
    """Test 1: Generates valid MySQL DDL with InnoDB, utf8mb4, and AUTO_INCREMENT."""
    schema = DatabaseSchema(
        provider="mysql",
        database_name="users_db",
        tables=[
            TableDefinition(
                name="users",
                description="User accounts table",
                columns=[
                    ColumnDefinition(
                        name="id",
                        data_type="integer",
                        primary_key=True,
                        nullable=False,
                        unique=True,
                    ),
                    ColumnDefinition(
                        name="username",
                        data_type="varchar(255)",
                        nullable=False,
                        unique=True,
                    ),
                    ColumnDefinition(
                        name="email",
                        data_type="varchar",  # tests default to 255
                        nullable=False,
                    ),
                    ColumnDefinition(
                        name="created_at",
                        data_type="timestamp",
                    ),
                ],
            )
        ],
    )

    adapter = get_database_adapter("mysql")
    assert isinstance(adapter, MySQLAdapter)
    ddl = adapter.generate_ddl(schema)

    # Verifications
    assert "ENGINE=InnoDB" in ddl
    assert "DEFAULT CHARSET=utf8mb4" in ddl
    assert "AUTO_INCREMENT" in ddl
    assert "PRIMARY KEY" in ddl
    assert "VARCHAR(255)" in ddl
    assert "TIMESTAMP DEFAULT CURRENT_TIMESTAMP" in ddl


def test_mongodb_ir_and_script_generation():
    """Test 2: Generates valid MongoDB IR with collections, document_schema, and imperative script."""
    col = CollectionDefinition(
        name="products",
        description="Product catalog with embedded customer reviews",
        document_schema={
            "bsonType": "object",
            "required": ["name", "price"],
            "properties": {
                "name": {"bsonType": "string", "description": "Product name"},
                "price": {"bsonType": "double", "description": "Product price in USD"},
                "reviews": {
                    "bsonType": "array",
                    "description": "Embedded reviews list",
                    "items": {
                        "bsonType": "object",
                        "required": ["author", "rating"],
                        "properties": {
                            "author": {"bsonType": "string"},
                            "rating": {"bsonType": "int"},
                            "comment": {"bsonType": "string"},
                        },
                    },
                },
            },
        },
        indexes=[{"fields": ["name"], "unique": True}],
        embedded_documents=["reviews"],
    )

    ir = UniversalIR(
        intent="create_database",
        description="Product catalog with embedded reviews",
        database=DatabaseSchema(
            provider="mongodb",
            database_name="catalog_db",
            collections=[col],
        ),
    )

    # Validate IR structure
    assert ir.database.provider == "mongodb"
    assert len(ir.database.collections) == 1
    assert ir.database.collections[0].name == "products"
    assert "reviews" in ir.database.collections[0].embedded_documents

    adapter = get_database_adapter("mongodb")
    assert isinstance(adapter, MongoDBAdapter)
    script = adapter.generate_ddl(ir.database)

    assert 'db.createCollection("products"' in script
    assert "$jsonSchema" in script
    assert "reviews" in script
    assert "createIndex" in script


def test_mysql_execution(monkeypatch):
    """Test 3: ExecutionEngine connects and executes MySQL DDL."""
    schema = DatabaseSchema(
        provider="mysql",
        database_name="test_app_db",
        tables=[
            TableDefinition(
                name="users",
                columns=[
                    ColumnDefinition(name="id", data_type="integer", primary_key=True),
                    ColumnDefinition(name="email", data_type="varchar(100)"),
                ],
            )
        ],
    )

    # Test direct execution against running MySQL or validated mock
    try:
        import pymysql
        # Attempt connecting to local MySQL
        conn = pymysql.connect(host="localhost", port=3306, user="root", password="", connect_timeout=1)
        conn.close()
        res = execution_engine.execute_database(schema)
        assert res is True
    except Exception:
        # If external MySQL container is offline in unit test environment, verify mock execution
        executed_statements = []

        class MockCursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute(self, stmt):
                executed_statements.append(stmt)

        class MockConn:
            def cursor(self):
                return MockCursor()

            def close(self):
                pass

        monkeypatch.setattr(pymysql, "connect", lambda **kwargs: MockConn())
        res = execution_engine.execute_database(schema)
        assert res is True
        assert any("CREATE TABLE" in s for s in executed_statements)


def test_mongodb_execution():
    """Test 4: ExecutionEngine connects to local MongoDB, creates collection and applies JSON schema validator."""
    from pymongo import MongoClient

    mongo_url = os.getenv(
        "MONGODB_URL",
        "mongodb://root:rootpassword@localhost:27017/?authSource=admin"
    )
    try:
        # Check if local MongoDB is reachable
        client = MongoClient(mongo_url, serverSelectionTimeoutMS=2000)
        client.admin.command("ping")
    except Exception as e:
        pytest.skip(f"Local MongoDB not available on port 27017: {str(e)}")


    test_col_name = "test_products_catalog"
    db_name = "vellum_test_db"

    # Clean up previous test collection if exists
    db = client[db_name]
    db.drop_collection(test_col_name)

    schema = DatabaseSchema(
        provider="mongodb",
        database_name=db_name,
        collections=[
            CollectionDefinition(
                name=test_col_name,
                description="Products collection with JSON schema validation",
                document_schema={
                    "bsonType": "object",
                    "required": ["sku", "name"],
                    "properties": {
                        "sku": {"bsonType": "string"},
                        "name": {"bsonType": "string"},
                        "in_stock": {"bsonType": "bool"},
                    },
                },
                indexes=[{"fields": ["sku"], "unique": True}],
                embedded_documents=[],
            )
        ],
    )

    # Execute via ExecutionEngine
    success = execution_engine.execute_database(schema, connection_string=mongo_url)
    assert success is True

    # Verify collection was created in MongoDB
    collections = db.list_collection_names()
    assert test_col_name in collections

    # Verify index was created
    indexes = list(db[test_col_name].list_indexes())
    index_names = [idx["name"] for idx in indexes]
    assert any("sku" in name for name in index_names)

    # Clean up test collection
    db.drop_collection(test_col_name)
    client.close()
