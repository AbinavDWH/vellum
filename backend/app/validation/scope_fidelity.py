"""
Scope Fidelity Validation (F4).
Enforces that Vellum builds ONLY what the user asked for:
1. Every IR resource must map to an explicitly requested user entity or a strict technical dependency.
2. Databases (RDS, Aurora, PostgreSQL, MySQL, MongoDB tables/collections) are allowed ONLY when
   the user mentions data, storage, persistence, tables, or database.
3. Strict technical dependencies (e.g. IGW for public subnet, db_subnet_group for RDS, website config for static site)
   must be declared with an explicit reason ("Required because: ...").
4. Unmapped resources cause validation failure and reject the plan.
"""
from typing import Tuple, List, Dict, Any
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudResource


class ScopeFidelityValidator:
    """Validates that the generated plan matches the user's explicit scope without unsolicited extras."""

    DATABASE_KEYWORDS = [
        "database", "db", "postgres", "postgresql", "mysql", "mongodb", "mongo",
        "table", "tables", "schema", "entity", "entities", "data model",
        "persistence", "relational", "sql", "aurora", "dynamodb"
    ]

    STATIC_SITE_KEYWORDS = [
        "static site", "static website", "website", "html", "github",
        "frontend", "web app", "web page", "s3 website", "deploy site"
    ]

    STORAGE_KEYWORDS = [
        "s3", "bucket", "object storage", "blob", "files", "upload", "storage bucket"
    ]

    NETWORK_KEYWORDS = [
        "vpc", "network", "subnet", "virtual network", "cidr", "gateway", "igw", "route"
    ]

    CACHE_KEYWORDS = [
        "redis", "cache", "memcached", "elasticache"
    ]

    QUEUE_KEYWORDS = [
        "queue", "sqs", "sns", "pubsub", "topic"
    ]

    COMPUTE_KEYWORDS = [
        "ec2", "instance", "server", "vm", "compute", "container"
    ]

    @classmethod
    def analyze_user_intent(cls, prompt: str) -> Dict[str, bool]:
        p = prompt.lower()
        return {
            "wants_database": any(k in p for k in cls.DATABASE_KEYWORDS),
            "wants_static_site": any(k in p for k in cls.STATIC_SITE_KEYWORDS),
            "wants_storage": any(k in p for k in cls.STORAGE_KEYWORDS),
            "wants_network": any(k in p for k in cls.NETWORK_KEYWORDS),
            "wants_cache": any(k in p for k in cls.CACHE_KEYWORDS),
            "wants_queue": any(k in p for k in cls.QUEUE_KEYWORDS),
            "wants_compute": any(k in p for k in cls.COMPUTE_KEYWORDS),
        }

    @classmethod
    def validate(cls, prompt: str, ir: UniversalIR) -> Tuple[bool, List[str], UniversalIR]:
        """
        Validate scope fidelity.
        Returns (is_valid, error_messages, annotated_ir).
        Annotates technical dependencies with is_dependency=True and dependency_reason="...".
        """
        intents = cls.analyze_user_intent(prompt)
        errors: List[str] = []

        # 1. Database scope fidelity check
        has_database_schema = bool(ir.database and (ir.database.tables or ir.database.collections))
        has_cloud_db = False
        if ir.cloud and ir.cloud.resources:
            for r in ir.cloud.resources:
                if r.type in ["managed_database", "rds", "aws_db_instance", "database", "relational_database"]:
                    has_cloud_db = True
                    break

        if (has_database_schema or has_cloud_db) and not intents["wants_database"]:
            errors.append(
                "SCOPE_FIDELITY: Unrequested database resources created. "
                "Databases are permitted ONLY when the user explicitly requests data, storage, persistence, or tables."
            )

        # 2. Per-resource mapping and dependency classification
        if ir.cloud and ir.cloud.resources:
            has_public_subnet = any(
                r.type in ["subnet", "public_subnet", "aws_subnet"] and (
                    r.properties.get("map_public_ip_on_launch") is True
                    or r.properties.get("public") is True
                    or "public" in r.name.lower()
                )
                for r in ir.cloud.resources
            )
            has_s3_website = any(
                r.type in ["object_storage", "s3_bucket", "static_site", "website_hosting"] and (
                    r.properties.get("website") is True
                    or r.properties.get("static_site") is True
                    or "website" in r.name.lower()
                    or "site" in r.name.lower()
                )
                for r in ir.cloud.resources
            ) or ir.intent == "deploy_static_site"

            for res in ir.cloud.resources:
                r_type = res.type.lower()

                # Check if it's a known technical dependency
                if r_type in ["internet_gateway", "aws_internet_gateway", "igw"]:
                    if has_public_subnet:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: public subnet requires an Internet Gateway for internet access."
                        continue
                elif r_type in ["route_table", "aws_route_table", "route", "aws_route"]:
                    if has_public_subnet:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: public subnet requires route table entry (0.0.0.0/0 -> IGW)."
                        continue
                elif r_type in ["aws_s3_bucket_website_configuration", "aws_s3_bucket_public_access_block", "aws_s3_bucket_policy"]:
                    if has_s3_website:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: static website hosting requires website configuration and public read policy."
                        continue
                elif r_type in ["db_subnet_group", "aws_db_subnet_group"]:
                    if has_cloud_db and intents["wants_database"]:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: RDS instance requires a DB subnet group across availability zones."
                        continue
                elif r_type in ["security_group", "aws_security_group", "security_rule"]:
                    res.is_dependency = True
                    res.dependency_reason = "Required because: security group defines firewall boundaries for managed resources."
                    continue

                # Check primary user requests
                if r_type in ["virtual_network", "vpc", "subnet", "public_subnet", "private_subnet"]:
                    if not intents["wants_network"] and not (intents["wants_database"] and has_cloud_db):
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested network resource '{res.name}' ({res.type}) created when user did not request VPC or networking."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["object_storage", "s3_bucket", "storage_bucket", "static_site", "website_hosting"]:
                    if not (intents["wants_static_site"] or intents["wants_storage"]):
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested storage resource '{res.name}' ({res.type}) created when user did not request S3 or website."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["managed_database", "rds", "aws_db_instance", "database", "relational_database"]:
                    if not intents["wants_database"]:
                        # Already caught by database scope check
                        pass
                    else:
                        res.is_dependency = False

                elif r_type in ["elasticache_cluster", "redis"]:
                    if not intents["wants_cache"]:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested cache resource '{res.name}' created without cache intent."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["sqs_queue", "sns_topic"]:
                    if not intents["wants_queue"]:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested queue/topic resource '{res.name}' created without queue intent."
                        )
                    else:
                        res.is_dependency = False

        # Also populate assumptions with dependency reasons if not already present
        if ir.cloud and ir.cloud.resources:
            for res in ir.cloud.resources:
                if res.is_dependency and res.dependency_reason:
                    if not any(res.dependency_reason in a for a in ir.assumptions):
                        ir.assumptions.append(res.dependency_reason)

        is_valid = len(errors) == 0
        return is_valid, errors, ir
