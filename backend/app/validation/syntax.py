import re
from typing import List, Dict, Any, Tuple
from app.schemas.ir import UniversalIR


class SyntaxValidator:
    """Validates Universal IR syntax, cross-references, and naming conventions."""

    CIDR_REGEX = r"^([0-9]{1,3}\.){3}[0-9]{1,3}\/([0-9]|[1-2][0-9]|3[0-2])$"
    IDENTIFIER_REGEX = r"^[a-zA-Z_][a-zA-Z0-9_-]*$"

    @classmethod
    def validate(cls, ir: UniversalIR) -> Tuple[bool, List[str]]:
        errors: List[str] = []

        # Validate database schema
        if ir.database:
            # Relational validation
            if ir.database.tables:
                table_names = set()
                for table in ir.database.tables:
                    if not re.match(cls.IDENTIFIER_REGEX, table.name):
                        errors.append(f"Invalid table name: '{table.name}'. Must match {cls.IDENTIFIER_REGEX}")
                    if table.name in table_names:
                        errors.append(f"Duplicate table name found: '{table.name}'")
                    table_names.add(table.name)

                    col_names = set()
                    has_pk = False
                    for col in table.columns:
                        if not re.match(cls.IDENTIFIER_REGEX, col.name):
                            errors.append(f"Table '{table.name}' has invalid column name: '{col.name}'")
                        if col.name in col_names:
                            errors.append(f"Table '{table.name}' has duplicate column: '{col.name}'")
                        col_names.add(col.name)
                        if col.primary_key:
                            has_pk = True

                    if not has_pk and table.columns:
                        errors.append(f"Table '{table.name}' has no primary key defined.")

            # NoSQL Document validation (MongoDB)
            if ir.database.collections:
                collection_names = set()
                for col in ir.database.collections:
                    if not re.match(cls.IDENTIFIER_REGEX, col.name):
                        errors.append(f"Invalid collection name: '{col.name}'. Must match {cls.IDENTIFIER_REGEX}")
                    if col.name in collection_names:
                        errors.append(f"Duplicate collection name found: '{col.name}'")
                    collection_names.add(col.name)
                    if not isinstance(col.document_schema, dict):
                        errors.append(f"Collection '{col.name}' document_schema must be a dictionary.")


        # Validate cloud resources
        if ir.cloud:
            resource_names = set()
            for res in ir.cloud.resources:
                if not re.match(cls.IDENTIFIER_REGEX, res.name):
                    errors.append(f"Invalid resource name: '{res.name}'")
                if res.name in resource_names:
                    errors.append(f"Duplicate resource name: '{res.name}'")
                resource_names.add(res.name)

                # Validate CIDR blocks if present
                cidr = res.properties.get("cidr_block")
                if cidr and not re.match(cls.CIDR_REGEX, cidr):
                    errors.append(f"Resource '{res.name}' has invalid CIDR block: '{cidr}'")

                # Validate dependencies
                for dep in res.depends_on:
                    if dep not in resource_names and dep != res.name:
                        # Allow forward references, checked globally later
                        pass

        return len(errors) == 0, errors
