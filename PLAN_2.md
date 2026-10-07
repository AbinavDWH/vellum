# Vellum Phase 2 — Module M-09: Multi-Database Expansion (MySQL & MongoDB)

> Scope: backend (`adapters/database/`, `schemas/`, `llm/prompts.py`) and frontend schema viewer.
> Context: Phase 1 (PostgreSQL + AWS) is 100% complete. We are now proving the 
> "Provider Agnostic" architecture by adding a second relational DB (MySQL) 
> and our first NoSQL document DB (MongoDB).
> Rule: The Universal IR must remain the single source of truth. The LLM 
> generates IR; the adapters translate IR to engine-specific commands.

---

## 1. Universal IR Schema Updates (`backend/app/schemas/database.py`)

Update the Pydantic models to support NoSQL and MySQL concepts without breaking PostgreSQL.

```python
# Add to DatabasePlan model
class DatabasePlan(BaseModel):
    provider: Literal["postgresql", "mysql", "mongodb"]
    name: str
    # Relational (Postgres/MySQL)
    tables: Optional[List[Table]] = None
    relationships: Optional[List[Relationship]] = None
    # NoSQL (MongoDB)
    collections: Optional[List[Collection]] = None

class Collection(BaseModel):
    name: str
    document_schema: dict  # JSON Schema for MongoDB validation
    indexes: List[dict] = []
    embedded_documents: List[str] = [] # Denormalized relationships
```

---

## 2. MySQL Adapter (`backend/app/adapters/database/mysql.py`)

Implement the `DatabaseAdapter` interface for MySQL.

**Key MySQL-specific translations:**
1. `integer` + `auto_increment` → `INT AUTO_INCREMENT PRIMARY KEY`
2. `varchar` requires explicit length (default to 255 if missing).
3. `text` → `TEXT` (MySQL doesn't have `TEXT[]` arrays like Postgres; use `JSON` type for arrays).
4. `timestamp` → `TIMESTAMP DEFAULT CURRENT_TIMESTAMP`.
5. **Engine:** Always append `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4` to `CREATE TABLE`.

**Execution:** Use `pymysql` or `mysql-connector-python` to execute DDL.

---

## 3. MongoDB Adapter (`backend/app/adapters/database/mongodb.py`)

Implement the `DatabaseAdapter` interface for MongoDB.
*Note: MongoDB doesn't use DDL. It uses imperative commands to create collections and validation rules.*

**Key MongoDB translations:**
1. **Create Collection:** `db.create_collection(name)`
2. **Schema Validation:** Apply JSON Schema validation to the collection to enforce the structure defined by the LLM.
   ```javascript
   db.command({
       collMod: "collection_name",
       validator: { $jsonSchema: { ... } }
   })
   ```
3. **Indexes:** Translate IR indexes to `db.collection.create_index()`.
4. **Execution:** Use `pymongo` to connect and execute commands.

---

## 4. LLM Prompt Engineering (`backend/app/llm/prompts.py`)

Update the System Prompt for the LM Studio IR generation.
1. Teach the LLM the difference between Relational (Tables/Foreign Keys) and Document (Collections/Embedded JSON) modeling.
2. Add few-shot examples for MongoDB:
   * *User:* "I need a blog database. Posts have comments embedded inside them."
   * *LLM Output:* `{ "provider": "mongodb", "collections": [{ "name": "posts", "document_schema": {...}, "embedded_documents": ["comments"] }] }`

---

## 5. Frontend Schema Viewer (`frontend/src/components/PlanPreview/SchemaViewer.tsx`)

Update the UI to render MongoDB schemas.
1. If `provider === "postgresql" | "mysql"`: Render the existing relational table cards with PK/FK lines.
2. If `provider === "mongodb"`: Render "Document Cards" showing the JSON Schema structure, nested fields, and array types. Use a tree-view component for nested JSON schemas.

---

## 6. ✅ Checkpoint M-09

- [x] `test_module_9_databases.py` created and passing.
- [x] Test 1: NL prompt "Create a MySQL user table with auto-increment ID" → Generates valid MySQL DDL with `InnoDB`.
- [x] Test 2: NL prompt "Create a MongoDB product catalog with embedded reviews" → Generates valid IR with `collections` and `document_schema`.
- [x] Test 3: ExecutionEngine successfully connects to a local MySQL container and creates the table.
- [x] Test 4: ExecutionEngine successfully connects to a local MongoDB container, creates the collection, and applies the JSON schema validator.
- [x] Frontend Schema Viewer correctly renders the MongoDB document tree.
- [x] `npm run build` and `pytest` both pass green.

---

## 7. 🛡️ Verification & Quality Assurance Checklist (Layers 6–10)

- [x] **Layer 6:** All generated Terraform passes `terraform fmt` and `terraform validate`
- [x] **Layer 6:** All generated SQL is syntactically valid and follows best practices
- [x] **Layer 7:** Resources actually exist in LocalStack after execution
- [x] **Layer 7:** PostgreSQL tables are created with correct schema
- [x] **Layer 8:** Drift detection catches manual deletions and modifications
- [x] **Layer 9:** Security policies block public RDS, open ports, unencrypted S3
- [x] **Layer 10:** Large plans (30+ resources) generate in <30 seconds
- [x] **Layer 10:** System handles 20 concurrent requests without failure

*Vellum Phase 2 — October 04, 2026*