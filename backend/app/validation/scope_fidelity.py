"""
Scope Fidelity Validation (F4).
Enforces that Vellum builds ONLY what the user asked for:
1. Every IR resource must map to an explicitly requested user entity or a strict technical dependency.
2. Databases (RDS, Aurora, PostgreSQL, MySQL, MongoDB tables/collections) are allowed ONLY when
   the user mentions data, storage, persistence, tables, or database (matched as whole words).
3. Strict technical dependencies (e.g. IGW for public subnet, db_subnet_group for RDS, website config for static site)
   must be declared with an explicit reason ("Required because: ...").
4. Unmapped resources or resources not on the allowed list cause validation failure and reject the plan.
5. Security groups are NOT auto-allowed unless explicitly requested or strictly required by compute/database.
"""
import re
from typing import Tuple, List, Dict, Any, Optional
from app.schemas.ir import UniversalIR
from app.schemas.cloud import CloudResource


class ScopeFidelityValidator:
    """Validates that the generated plan matches the user's explicit scope without unsolicited extras."""

    # Strict allowed list of recognized resource types
    ALLOWED_RESOURCE_TYPES = {
        # Networking
        "virtual_network", "vpc", "network", "aws_vpc",
        "subnet", "public_subnet", "private_subnet", "aws_subnet",
        "internet_gateway", "aws_internet_gateway", "igw",
        "nat_gateway", "aws_nat_gateway",
        "elastic_ip", "eip", "aws_eip",
        "route_table", "aws_route_table",
        "route", "aws_route",
        "route_table_association", "aws_route_table_association",
        "security_group", "aws_security_group", "security_rule", "sg",
        "load_balancer", "alb", "aws_lb", "aws_alb",
        "listener", "target_group", "aws_lb_target_group", "aws_lb_listener",

        # Databases
        "managed_database", "rds", "rds_instance", "db_instance", "database",
        "relational_database", "aws_db_instance",
        "db_subnet_group", "aws_db_subnet_group", "rds_subnet_group", "subnet_group",

        # Storage
        "object_storage", "s3_bucket", "storage_bucket", "bucket", "s3", "aws_s3_bucket",
        "static_site", "website_hosting", "website",
        "bucket_versioning", "aws_s3_bucket_versioning",
        "bucket_encryption", "aws_s3_bucket_server_side_encryption_configuration",
        "bucket_public_access_block",
        "aws_s3_bucket_website_configuration", "aws_s3_bucket_public_access_block", "aws_s3_bucket_policy",

        # Compute
        "compute_instance", "ec2", "instance", "server", "aws_instance",
        "lambda", "lambda_function", "aws_lambda_function",

        # Caching
        "elasticache", "elasticache_cluster", "cache", "cache_cluster", "redis", "redis_cluster",
        "aws_elasticache_cluster", "aws_elasticache_replication_group",
        "elasticache_replication_group", "elasticache_subnet_group",

        # Messaging / NoSQL
        "sqs", "sqs_queue", "queue", "aws_sqs_queue",
        "sns", "sns_topic", "topic", "aws_sns_topic",
        "dynamodb", "dynamodb_table", "aws_dynamodb_table",

        # Security & Secrets & IAM
        "secret", "secretsmanager", "secrets_manager", "aws_secretsmanager_secret",
        "iam_role", "role", "aws_iam_role",
    }

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
        "vpc", "network", "subnet", "virtual network", "cidr", "gateway", "igw", "route",
        "security group", "security groups", "firewall", "load balancer", "alb",
        "nat", "nat gateway", "nat_gateway", "eip", "elastic ip", "elastic_ip"
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
    def _matches_whole_word(cls, keyword: str, text: str) -> bool:
        """Match whole words only so 'feedback' does not match 'db'."""
        pattern = r'(?:\b|_)' + re.escape(keyword) + r'(?:\b|_)'
        return bool(re.search(pattern, text, re.IGNORECASE))

    @classmethod
    def analyze_user_intent(cls, prompt: str) -> Dict[str, bool]:
        """Analyze intent across whole words in prompt and session context."""
        return {
            "wants_database": any(cls._matches_whole_word(k, prompt) for k in cls.DATABASE_KEYWORDS),
            "wants_static_site": any(cls._matches_whole_word(k, prompt) for k in cls.STATIC_SITE_KEYWORDS),
            "wants_storage": any(cls._matches_whole_word(k, prompt) for k in cls.STORAGE_KEYWORDS),
            "wants_network": any(cls._matches_whole_word(k, prompt) for k in cls.NETWORK_KEYWORDS),
            "wants_cache": any(cls._matches_whole_word(k, prompt) for k in cls.CACHE_KEYWORDS),
            "wants_queue": any(cls._matches_whole_word(k, prompt) for k in cls.QUEUE_KEYWORDS),
            "wants_compute": any(cls._matches_whole_word(k, prompt) for k in cls.COMPUTE_KEYWORDS),
        }

    @classmethod
    def validate(
        cls,
        prompt: str,
        ir: UniversalIR,
        requirements_md: Optional[str] = None,
    ) -> Tuple[bool, List[str], UniversalIR]:
        """
        Validate scope fidelity against the whole session (requirements.md + prompt).
        Returns (is_valid, error_messages, annotated_ir).
        Annotates technical dependencies with is_dependency=True and dependency_reason="...".
        """
        session_text = f"{prompt}\n\n{requirements_md or ''}"
        intents = cls.analyze_user_intent(session_text)
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

        # 2. Check each resource against allowed list and session scope
        if ir.cloud and ir.cloud.resources:
            has_public_subnet = any(
                r.type in ["subnet", "public_subnet", "aws_subnet"] and (
                    r.properties.get("map_public_ip_on_launch") is True
                    or r.properties.get("public") is True
                    or "public" in r.name.lower()
                )
                for r in ir.cloud.resources
            )
            has_nat_gateway = any(
                r.type.lower().strip() in ["nat_gateway", "aws_nat_gateway"]
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

            has_compute_or_db = has_cloud_db or any(
                r.type in ["compute_instance", "ec2", "instance", "server", "aws_instance", "load_balancer", "alb"]
                for r in ir.cloud.resources
            )

            for res in ir.cloud.resources:
                r_type = res.type.lower().strip()

                # Rule: Resource type must be on the allowed list
                if r_type not in cls.ALLOWED_RESOURCE_TYPES:
                    errors.append(
                        f"SCOPE_FIDELITY: Resource type '{res.type}' is not recognized or permitted on the allowed list."
                    )
                    continue

                # Technical dependency mapping
                if r_type in ["internet_gateway", "aws_internet_gateway", "igw"]:
                    if has_public_subnet:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: public subnet requires an Internet Gateway for internet access."
                        continue
                elif r_type in ["elastic_ip", "eip", "aws_eip"]:
                    if has_nat_gateway:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: AWS NAT Gateway requires an Elastic IP (EIP) allocation."
                        continue
                    elif intents["wants_network"] or any(cls._matches_whole_word(k, session_text) for k in ["elastic ip", "eip"]):
                        res.is_dependency = False
                        continue
                    else:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested Elastic IP '{res.name}' ({res.type}) created without NAT Gateway or networking intent."
                        )
                        continue
                elif r_type in ["route_table", "aws_route_table", "route", "aws_route"]:
                    if has_public_subnet or has_nat_gateway:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: public subnet or NAT gateway requires route table entry."
                        continue
                elif r_type in [
                    "aws_s3_bucket_website_configuration", "aws_s3_bucket_public_access_block", "aws_s3_bucket_policy",
                    "bucket_versioning", "aws_s3_bucket_versioning", "bucket_encryption",
                    "aws_s3_bucket_server_side_encryption_configuration", "bucket_public_access_block"
                ]:
                    has_s3 = any(r.type.lower().strip() in ["object_storage", "s3_bucket", "storage_bucket", "bucket", "s3", "aws_s3_bucket"] for r in ir.cloud.resources)
                    if has_s3_website or has_s3:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: S3 bucket configuration dependency."
                        continue
                elif r_type in ["db_subnet_group", "aws_db_subnet_group", "rds_subnet_group", "subnet_group"]:
                    if has_cloud_db and intents["wants_database"]:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: RDS instance requires a DB subnet group across availability zones."
                        continue

                # Security groups: DO NOT auto-allow.
                # Must be requested by user OR strictly required by compute / database / load balancer.
                if r_type in ["security_group", "aws_security_group", "security_rule", "sg"]:
                    user_requested_sg = intents["wants_network"] or any(
                        cls._matches_whole_word(k, session_text) for k in ["security group", "security groups", "firewall", "sg"]
                    )
                    if user_requested_sg:
                        res.is_dependency = False
                    elif has_compute_or_db:
                        res.is_dependency = True
                        res.dependency_reason = "Required because: compute/database resource requires security group firewall rules."
                    else:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested security group '{res.name}' ({res.type}) created when user did not request network, compute, or database infrastructure."
                        )
                    continue

                # Check primary user requests
                if r_type in ["virtual_network", "vpc", "subnet", "public_subnet", "private_subnet", "aws_vpc", "aws_subnet", "nat_gateway", "aws_nat_gateway"]:
                    if not intents["wants_network"] and not (intents["wants_database"] and has_cloud_db):
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested network resource '{res.name}' ({res.type}) created when user did not request VPC or networking."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["object_storage", "s3_bucket", "storage_bucket", "static_site", "website_hosting", "bucket", "s3", "aws_s3_bucket"]:
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

                elif r_type in ["elasticache_cluster", "redis", "elasticache", "cache", "cache_cluster", "aws_elasticache_cluster"]:
                    if not intents["wants_cache"]:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested cache resource '{res.name}' created without cache intent."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["sqs_queue", "sns_topic", "sqs", "sns", "queue", "topic", "aws_sqs_queue", "aws_sns_topic"]:
                    if not intents["wants_queue"]:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested queue/topic resource '{res.name}' created without queue intent."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["compute_instance", "ec2", "instance", "server", "aws_instance"]:
                    if not intents["wants_compute"]:
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested compute resource '{res.name}' created without compute intent."
                        )
                    else:
                        res.is_dependency = False

                elif r_type in ["load_balancer", "alb", "aws_lb", "aws_alb"]:
                    if not intents["wants_network"] and not cls._matches_whole_word("load balancer", session_text) and not cls._matches_whole_word("alb", session_text):
                        errors.append(
                            f"SCOPE_FIDELITY: Unrequested load balancer '{res.name}' created without load balancer intent."
                        )
                    else:
                        res.is_dependency = False

        # Populate assumptions with dependency reasons
        if ir.cloud and ir.cloud.resources:
            for res in ir.cloud.resources:
                if res.is_dependency and res.dependency_reason:
                    if not any(res.dependency_reason in a for a in ir.assumptions):
                        ir.assumptions.append(res.dependency_reason)

        is_valid = len(errors) == 0
        return is_valid, errors, ir
