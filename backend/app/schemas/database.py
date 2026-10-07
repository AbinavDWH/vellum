from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field, model_validator


class ColumnDefinition(BaseModel):
    name: str
    data_type: str = "varchar(255)"  # e.g., "serial", "integer", "varchar(255)", "text", "timestamp", "boolean"
    primary_key: bool = False
    nullable: bool = True
    unique: bool = False
    default: Optional[str] = None
    references: Optional[str] = None  # e.g., "departments(id)"
    description: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def normalize_column(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize references if given as dict or list
            ref = data.get("references")
            if isinstance(ref, dict):
                tbl = ref.get("table") or ref.get("ref_table") or ""
                col = ref.get("column") or ref.get("ref_column") or "id"
                data["references"] = f"{tbl}({col})" if tbl else None
            elif isinstance(ref, (list, tuple)) and len(ref) >= 2:
                data["references"] = f"{ref[0]}({ref[1]})"

            # Normalize default to string
            if "default" in data and data["default"] is not None and not isinstance(data["default"], str):
                data["default"] = str(data["default"])

            # Ensure data_type exists
            if not data.get("data_type"):
                data["data_type"] = "varchar(255)"
        return data


class IndexDefinition(BaseModel):
    name: str
    columns: List[str]
    unique: bool = False


class ForeignKeyDefinition(BaseModel):
    name: Optional[str] = None
    columns: List[str] = Field(default_factory=list)
    ref_table: str = ""
    ref_columns: List[str] = Field(default_factory=list)
    on_delete: Optional[str] = "CASCADE"
    on_update: Optional[str] = "CASCADE"

    @model_validator(mode="before")
    @classmethod
    def normalize_fk(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Support singular column -> columns list
            if "column" in data and not data.get("columns"):
                val = data["column"]
                data["columns"] = [val] if isinstance(val, str) else list(val)
            if "ref_column" in data and not data.get("ref_columns"):
                val = data["ref_column"]
                data["ref_columns"] = [val] if isinstance(val, str) else list(val)
            if "referenced_table" in data and not data.get("ref_table"):
                data["ref_table"] = str(data["referenced_table"])
            if "referenced_columns" in data and not data.get("ref_columns"):
                val = data["referenced_columns"]
                data["ref_columns"] = list(val) if isinstance(val, (list, tuple)) else [str(val)]
            if "referenced_column" in data and not data.get("ref_columns"):
                data["ref_columns"] = [str(data["referenced_column"])]
            if data.get("columns") is None:
                data["columns"] = []
            elif isinstance(data["columns"], str):
                data["columns"] = [data["columns"]]
            if data.get("ref_columns") is None:
                data["ref_columns"] = []
            elif isinstance(data["ref_columns"], str):
                data["ref_columns"] = [data["ref_columns"]]
            if not data.get("ref_table"):
                data["ref_table"] = ""
        return data


class TableDefinition(BaseModel):
    name: str
    description: Optional[str] = None
    columns: List[ColumnDefinition] = Field(default_factory=list)
    indexes: List[IndexDefinition] = Field(default_factory=list)
    foreign_keys: List[ForeignKeyDefinition] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def sanitize_table(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for k in ["columns", "indexes", "foreign_keys"]:
                if data.get(k) is None:
                    data[k] = []
        return data


# Phase 2 M-09: NoSQL Document Model for MongoDB
class CollectionDefinition(BaseModel):
    name: str
    document_schema: Dict[str, Any] = Field(default_factory=dict)  # JSON Schema for MongoDB validation
    indexes: List[Dict[str, Any]] = Field(default_factory=list)
    embedded_documents: List[str] = Field(default_factory=list)  # Denormalized relationships
    description: Optional[str] = None


Collection = CollectionDefinition
Table = TableDefinition
Relationship = ForeignKeyDefinition


class DatabaseSchema(BaseModel):
    provider: Literal["postgresql", "mysql", "mongodb"] = "postgresql"
    database_name: str = "app_db"
    name: Optional[str] = None
    # Relational (PostgreSQL / MySQL)
    tables: List[TableDefinition] = Field(default_factory=list)
    relationships: Optional[List[ForeignKeyDefinition]] = None
    views: List[Dict[str, Any]] = Field(default_factory=list)
    extensions: List[str] = Field(default_factory=list)  # e.g., ["uuid-ossp"]
    # NoSQL (MongoDB)
    collections: List[CollectionDefinition] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def sync_name_and_database_name(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Normalize provider
            prov = str(data.get("provider") or "postgresql").lower().strip()
            if prov not in ["postgresql", "mysql", "mongodb"]:
                prov = "postgresql"
            data["provider"] = prov

            # Clean lists if None
            for k in ["tables", "views", "extensions", "collections"]:
                if data.get(k) is None:
                    data[k] = []

            if "name" in data and "database_name" not in data:
                data["database_name"] = str(data["name"])
            elif "database_name" in data and "name" not in data:
                data["name"] = str(data["database_name"])
            elif "database_name" not in data and "name" not in data:
                data["database_name"] = "app_db"
                data["name"] = "app_db"
        return data


DatabasePlan = DatabaseSchema

