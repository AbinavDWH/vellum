import re
from typing import Dict, Any, List, Optional, Callable
from app.adapters.cloud.base import CloudProviderAdapter
from app.config import settings


class AWSAdapter(CloudProviderAdapter):
    """AWS implementation."""

    MAPPING = {
        # Networking
        "virtual_network": "aws_vpc",
        "vpc": "aws_vpc",
        "network": "aws_vpc",
        "aws_vpc": "aws_vpc",
        "subnet": "aws_subnet",
        "public_subnet": "aws_subnet",
        "private_subnet": "aws_subnet",
        "aws_subnet": "aws_subnet",
        "security_group": "aws_security_group",
        "security_rule": "aws_security_group",
        "sg": "aws_security_group",
        "aws_security_group": "aws_security_group",
        "security_group_rule": "aws_security_group_rule",
        "aws_security_group_rule": "aws_security_group_rule",
        "internet_gateway": "aws_internet_gateway",
        "igw": "aws_internet_gateway",
        "gateway": "aws_internet_gateway",
        "aws_internet_gateway": "aws_internet_gateway",
        "nat_gateway": "aws_nat_gateway",
        "nat": "aws_nat_gateway",
        "aws_nat_gateway": "aws_nat_gateway",
        "eip": "aws_eip",
        "elastic_ip": "aws_eip",
        "aws_eip": "aws_eip",
        "route_table": "aws_route_table",
        "aws_route_table": "aws_route_table",
        "route": "aws_route",
        "aws_route": "aws_route",
        "route_table_association": "aws_route_table_association",
        "subnet_route_table_association": "aws_route_table_association",
        "aws_route_table_association": "aws_route_table_association",

        # Databases
        "managed_database": "aws_db_instance",
        "database": "aws_db_instance",
        "rds": "aws_db_instance",
        "rds_instance": "aws_db_instance",
        "db_instance": "aws_db_instance",
        "database_instance": "aws_db_instance",
        "managed_database_instance": "aws_db_instance",
        "aws_db_instance": "aws_db_instance",
        "db_subnet_group": "aws_db_subnet_group",
        "rds_subnet_group": "aws_db_subnet_group",
        "subnet_group": "aws_db_subnet_group",
        "database_subnet_group": "aws_db_subnet_group",
        "managed_database_subnet_group": "aws_db_subnet_group",
        "aws_db_subnet_group": "aws_db_subnet_group",

        # Caching
        "elasticache": "aws_elasticache_cluster",
        "elasticache_cluster": "aws_elasticache_cluster",
        "cache": "aws_elasticache_cluster",
        "cache_cluster": "aws_elasticache_cluster",
        "redis": "aws_elasticache_cluster",
        "memcached": "aws_elasticache_cluster",
        "redis_cluster": "aws_elasticache_replication_group",
        "elasticache_replication_group": "aws_elasticache_replication_group",
        "cache_subnet_group": "aws_elasticache_subnet_group",
        "elasticache_subnet_group": "aws_elasticache_subnet_group",
        "aws_elasticache_cluster": "aws_elasticache_cluster",
        "aws_elasticache_replication_group": "aws_elasticache_replication_group",
        "aws_elasticache_subnet_group": "aws_elasticache_subnet_group",

        # Storage
        "object_storage": "aws_s3_bucket",
        "storage_bucket": "aws_s3_bucket",
        "s3_bucket": "aws_s3_bucket",
        "bucket": "aws_s3_bucket",
        "s3": "aws_s3_bucket",
        "aws_s3_bucket": "aws_s3_bucket",
        "static_site": "aws_s3_bucket",
        "website_hosting": "aws_s3_bucket",
        "website": "aws_s3_bucket",

        # S3 Features & Child Resources
        "bucket_versioning": "aws_s3_bucket_versioning",
        "object_storage_versioning": "aws_s3_bucket_versioning",
        "s3_versioning": "aws_s3_bucket_versioning",
        "s3_bucket_versioning": "aws_s3_bucket_versioning",
        "aws_bucket_versioning": "aws_s3_bucket_versioning",
        "aws_s3_bucket_versioning": "aws_s3_bucket_versioning",

        "bucket_encryption": "aws_s3_bucket_server_side_encryption_configuration",
        "object_storage_encryption": "aws_s3_bucket_server_side_encryption_configuration",
        "s3_encryption": "aws_s3_bucket_server_side_encryption_configuration",
        "s3_bucket_encryption": "aws_s3_bucket_server_side_encryption_configuration",
        "aws_bucket_encryption": "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_bucket_encryption": "aws_s3_bucket_server_side_encryption_configuration",
        "bucket_server_side_encryption_configuration": "aws_s3_bucket_server_side_encryption_configuration",
        "object_storage_server_side_encryption_configuration": "aws_s3_bucket_server_side_encryption_configuration",
        "aws_s3_bucket_server_side_encryption_configuration": "aws_s3_bucket_server_side_encryption_configuration",

        "bucket_public_access_block": "aws_s3_bucket_public_access_block",
        "object_storage_public_access_block": "aws_s3_bucket_public_access_block",
        "s3_public_access_block": "aws_s3_bucket_public_access_block",
        "s3_bucket_public_access_block": "aws_s3_bucket_public_access_block",
        "aws_bucket_public_access_block": "aws_s3_bucket_public_access_block",
        "aws_s3_bucket_public_access_block": "aws_s3_bucket_public_access_block",

        "bucket_website_configuration": "aws_s3_bucket_website_configuration",
        "object_storage_website_configuration": "aws_s3_bucket_website_configuration",
        "s3_website_configuration": "aws_s3_bucket_website_configuration",
        "aws_s3_bucket_website_configuration": "aws_s3_bucket_website_configuration",

        "bucket_policy": "aws_s3_bucket_policy",
        "object_storage_policy": "aws_s3_bucket_policy",
        "s3_policy": "aws_s3_bucket_policy",
        "s3_bucket_policy": "aws_s3_bucket_policy",
        "aws_s3_bucket_policy": "aws_s3_bucket_policy",

        # Compute
        "compute_instance": "aws_instance",
        "ec2": "aws_instance",
        "instance": "aws_instance",
        "server": "aws_instance",
        "virtual_machine": "aws_instance",
        "vm": "aws_instance",
        "aws_instance": "aws_instance",

        # Messaging & NoSQL
        "sqs": "aws_sqs_queue",
        "sqs_queue": "aws_sqs_queue",
        "queue": "aws_sqs_queue",
        "aws_sqs_queue": "aws_sqs_queue",
        "sns": "aws_sns_topic",
        "sns_topic": "aws_sns_topic",
        "topic": "aws_sns_topic",
        "aws_sns_topic": "aws_sns_topic",
        "dynamodb": "aws_dynamodb_table",
        "dynamodb_table": "aws_dynamodb_table",
        "nosql_table": "aws_dynamodb_table",
        "aws_dynamodb_table": "aws_dynamodb_table",

        # Security & Secrets & IAM
        "secret": "aws_secretsmanager_secret",
        "secretsmanager": "aws_secretsmanager_secret",
        "secrets_manager": "aws_secretsmanager_secret",
        "aws_secretsmanager_secret": "aws_secretsmanager_secret",
        "iam_role": "aws_iam_role",
        "role": "aws_iam_role",
        "aws_iam_role": "aws_iam_role",
        "lambda": "aws_lambda_function",
        "lambda_function": "aws_lambda_function",
        "aws_lambda_function": "aws_lambda_function",
    }

    def get_provider_name(self) -> str:
        return "aws"

    def get_local_endpoint(self) -> str:
        return ""

    @staticmethod
    def _clean_tf_ref(
        val: Any,
        target_type: str,
        default_name: Optional[str] = None,
        mapped_resources: Optional[List[Dict[str, Any]]] = None,
        attr: str = "id",
        filter_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> str:
        """
        Produce a valid HCL Terraform resource reference or literal identifier.
        Eliminates malformed interpolations like aws_subnet.${foo.id}.id or "${foo.id}".
        """
        if not val:
            if mapped_resources:
                candidates = [r for r in mapped_resources if r.get("tf_type") == target_type]
                if filter_fn:
                    filtered = [r for r in candidates if filter_fn(r)]
                    if filtered:
                        candidates = filtered
                if candidates:
                    return f"{target_type}.{candidates[0]['name']}.{attr}"
            if default_name:
                return f"{target_type}.{default_name}.{attr}"
            return f"{target_type}.main.{attr}"

        s = str(val).strip()
        # Strip outer quotes if any
        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
            s = s[1:-1].strip()

        # Check for literal AWS ARNs
        if s.startswith("arn:"):
            return f'"{s}"'

        # Only treat a value as a real AWS ID if it has the correct shape:
        # prefix followed by a run of hex characters (8 to 32 chars, e.g. subnet-0abc123def456789a or vpc-12345678).
        # Any other value (e.g. vpc-main, subnet-public, sg-web) is a resource name and treated as a Terraform reference.
        if re.match(r"^(?:subnet|vpc|igw|rtb|eipalloc|vol|ami|sg|tg|nat)-[0-9a-fA-F]{8,32}$", s):
            return f'"{s}"'

        # Strip ${ ... }
        if s.startswith("${") and s.endswith("}"):
            s = s[2:-1].strip()

        # If s has a resource prefix like "aws_subnet." or "aws_vpc."
        if s.startswith("aws_"):
            parts = s.split(".")
            if len(parts) >= 2:
                res_type_part = parts[0]
                res_name_part = parts[1]
                attr_part = parts[2] if len(parts) >= 3 else attr
                if mapped_resources:
                    clean_res = res_name_part.replace("-", "_")
                    match = next((r["name"] for r in mapped_resources if r.get("tf_type") == res_type_part and r.get("name") in (res_name_part, clean_res)), None)
                    res_name_part = match or clean_res
                else:
                    res_name_part = res_name_part.replace("-", "_")
                return f"{res_type_part}.{res_name_part}.{attr_part}"

        # If s is in format "resource_name.id" or "resource_name.arn"
        if "." in s:
            parts = s.split(".")
            res_name = parts[0]
            attr_part = parts[1] if len(parts) > 1 else attr
            if mapped_resources:
                clean_res = res_name.replace("-", "_")
                match = next((r["name"] for r in mapped_resources if r.get("tf_type") == target_type and r.get("name") in (res_name, clean_res)), None)
                res_name = match or clean_res
            else:
                res_name = res_name.replace("-", "_")
            return f"{target_type}.{res_name}.{attr_part}"

        # Otherwise s is just the logical resource name, e.g. "nat_eip", "public_subnet_1a", "vpc-main"
        res_name = s
        if mapped_resources:
            clean_res = res_name.replace("-", "_")
            match = next((r["name"] for r in mapped_resources if r.get("tf_type") == target_type and r.get("name") in (res_name, clean_res)), None)
            res_name = match or clean_res
        else:
            res_name = res_name.replace("-", "_")
        return f"{target_type}.{res_name}.{attr}"

    def map_resources(self, universal_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
        cloud = universal_ir.get("cloud")
        if not cloud or not cloud.get("resources"):
            return []

        mapped = []
        for res in cloud["resources"]:
            res_type = res.get("type", "").lower().strip()
            name = res.get("name", "unnamed").replace("-", "_").replace(" ", "_")
            props = res.get("properties", {}) or {}

            # Auto-detect subnets if loosely categorized as virtual_network/network/vpc
            if res_type in ["virtual_network", "network", "vpc"] and (
                "subnet" in name.lower() or "/24" in str(props.get("cidr_block", "")) or "/28" in str(props.get("cidr_block", ""))
            ):
                res_type = "subnet"

            clean_type = res_type[4:] if res_type.startswith("aws_") else res_type
            if res_type in self.MAPPING:
                tf_type = self.MAPPING[res_type]
            elif clean_type in self.MAPPING:
                tf_type = self.MAPPING[clean_type]
            elif res_type.startswith("aws_"):
                tf_type = res_type
            else:
                tf_type = self.MAPPING.get(res_type, f"aws_{res_type}")

            mapped.append({
                "universal_type": res_type,
                "tf_type": tf_type,
                "name": name,
                "properties": props,
                "depends_on": [d.replace("-", "_") for d in (res.get("depends_on") or [])],
                "tags": res.get("tags") or {},
            })
        return mapped

    def generate_terraform(
        self,
        mapped_resources: Any,
        environment: str = "prod",
        region: Optional[str] = None,
    ) -> str:
        from app.schemas.ir import UniversalIR
        if isinstance(mapped_resources, UniversalIR):
            if mapped_resources.cloud:
                environment = mapped_resources.cloud.environment or environment
                region = mapped_resources.cloud.region or region
            mapped_resources = self.map_resources(mapped_resources.model_dump())
        elif isinstance(mapped_resources, dict) and "cloud" in mapped_resources:
            c_env = mapped_resources.get("cloud", {}).get("environment")
            if c_env:
                environment = c_env
            c_reg = mapped_resources.get("cloud", {}).get("region")
            if c_reg:
                region = c_reg
            mapped_resources = self.map_resources(mapped_resources)

        blocks: List[str] = []

        # 1. Terraform Block & Provider
        import re
        raw_region = region or getattr(settings, "DEFAULT_AWS_REGION", "us-east-1") or "us-east-1"
        target_region = re.sub(r"^([a-z]{2}-[a-z]+-\d+)[a-z]$", r"\1", raw_region)

        provider_block = f"""# ========================================================
# Generated by Vellum - Autonomous Infrastructure Designer
# Provider: AWS Cloud ({environment.upper()})
# ========================================================

terraform {{
  required_version = ">= 1.5.0"
  required_providers {{
    aws = {{
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }}
  }}
}}

provider "aws" {{
  region = "{target_region}"
}}
"""
        blocks.append(provider_block)

        # Track created resources for outputs and relations
        vpcs = [r for r in mapped_resources if r["tf_type"] == "aws_vpc"]
        default_vpc_ref = f"aws_vpc.{vpcs[0]['name']}.id" if vpcs else None

        # Check for public subnets (or resources needing internet connectivity)
        public_subnets = [
            r for r in mapped_resources
            if r["tf_type"] == "aws_subnet" and (
                r["properties"].get("map_public_ip_on_launch") is True
                or r["properties"].get("public") is True
                or r["properties"].get("is_public") is True
                or "public" in r["name"].lower()
                or "public" in str(r.get("universal_type", "")).lower()
            )
        ]

        if public_subnets and vpcs:
            main_vpc_name = vpcs[0]["name"]
            # 1. Internet Gateway
            existing_igw = next((r for r in mapped_resources if r["tf_type"] == "aws_internet_gateway"), None)
            if not existing_igw:
                igw_name = f"{main_vpc_name}_igw"
                mapped_resources.append({
                    "universal_type": "internet_gateway",
                    "tf_type": "aws_internet_gateway",
                    "name": igw_name,
                    "properties": {"vpc_name": main_vpc_name},
                    "depends_on": [main_vpc_name],
                    "tags": {},
                })
            else:
                igw_name = existing_igw["name"]

            # 2. Public Route Table
            existing_rt = next(
                (r for r in mapped_resources if r["tf_type"] == "aws_route_table" and ("public" in r["name"].lower() or r["properties"].get("public") is True)),
                None
            )
            if not existing_rt:
                rt_name = f"{main_vpc_name}_public_rt"
                mapped_resources.append({
                    "universal_type": "route_table",
                    "tf_type": "aws_route_table",
                    "name": rt_name,
                    "properties": {"vpc_name": main_vpc_name, "public": True},
                    "depends_on": [main_vpc_name],
                    "tags": {},
                })
            else:
                rt_name = existing_rt["name"]

            # 3. Route 0.0.0.0/0 -> IGW
            existing_route = next(
                (r for r in mapped_resources if r["tf_type"] == "aws_route" and r["properties"].get("destination_cidr_block") == "0.0.0.0/0"),
                None
            )
            if not existing_route:
                route_name = f"{main_vpc_name}_public_internet"
                mapped_resources.append({
                    "universal_type": "aws_route",
                    "tf_type": "aws_route",
                    "name": route_name,
                    "properties": {
                        "route_table_name": rt_name,
                        "destination_cidr_block": "0.0.0.0/0",
                        "gateway_name": igw_name,
                    },
                    "depends_on": [rt_name, igw_name],
                    "tags": {},
                })

            # 4. Route Table Association for each public subnet
            for ps in public_subnets:
                sub_name = ps["name"]
                existing_assoc = next(
                    (r for r in mapped_resources if r["tf_type"] == "aws_route_table_association" and r["properties"].get("subnet_name") == sub_name),
                    None
                )
                if not existing_assoc:
                    mapped_resources.append({
                        "universal_type": "aws_route_table_association",
                        "tf_type": "aws_route_table_association",
                        "name": f"{sub_name}_assoc",
                        "properties": {
                            "subnet_name": sub_name,
                            "route_table_name": rt_name,
                        },
                        "depends_on": [sub_name, rt_name],
                        "tags": {},
                    })

        # 5. Ensure NAT Gateway has an Elastic IP if not explicitly mapped
        nat_gateways = [r for r in mapped_resources if r["tf_type"] == "aws_nat_gateway"]
        eips = [r for r in mapped_resources if r["tf_type"] == "aws_eip"]
        if nat_gateways and not eips:
            for ng in nat_gateways:
                eip_name = f"{ng['name']}_eip"
                mapped_resources.insert(0, {
                    "universal_type": "elastic_ip",
                    "tf_type": "aws_eip",
                    "name": eip_name,
                    "properties": {},
                    "depends_on": [],
                    "tags": {},
                })

        for res in mapped_resources:
            tf_type = res["tf_type"]
            name = res["name"]
            props = res["properties"]

            # Emit native Terraform 1.5+ import block if pre-flight resolved as reuse
            if props.get("_preflight_action") == "reuse":
                target_id = props.get("_preflight_target_id")
                if not target_id:
                    if tf_type == "aws_s3_bucket":
                        target_id = props.get("bucket_name") or name.replace("_", "-")
                    elif tf_type == "aws_db_instance":
                        target_id = props.get("identifier") or name.replace("_", "-")
                    else:
                        target_id = name
                blocks.append(f"""import {{
  to = {tf_type}.{name}
  id = "{target_id}"
}}
""")

            if tf_type == "aws_vpc":
                cidr = props.get("cidr_block", "10.0.0.0/16")
                blocks.append(f"""resource "aws_vpc" "{name}" {{
  cidr_block           = "{cidr}"
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_subnet":
                cidr = props.get("cidr_block", "10.0.1.0/24")
                default_reg = getattr(settings, "DEFAULT_AWS_REGION", "us-east-1")
                az = props.get("availability_zone", f"{default_reg}a")
                vpc_ref = self._clean_tf_ref(props.get("vpc_name") or props.get("vpc_id"), "aws_vpc", default_name=vpcs[0]['name'] if vpcs else 'main_vpc', mapped_resources=mapped_resources)
                is_public = bool(
                    props.get("map_public_ip_on_launch") is True
                    or props.get("public") is True
                    or props.get("is_public") is True
                    or "public" in name.lower()
                    or "public" in str(res.get("universal_type", "")).lower()
                )
                map_pub = "true" if is_public else "false"
                blocks.append(f"""resource "aws_subnet" "{name}" {{
  vpc_id                  = {vpc_ref}
  cidr_block              = "{cidr}"
  availability_zone       = "{az}"
  map_public_ip_on_launch = {map_pub}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_internet_gateway":
                vpc_ref = self._clean_tf_ref(props.get("vpc_name") or props.get("vpc_id"), "aws_vpc", default_name=vpcs[0]['name'] if vpcs else 'main_vpc', mapped_resources=mapped_resources)
                blocks.append(f"""resource "aws_internet_gateway" "{name}" {{
  vpc_id = {vpc_ref}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_route_table":
                vpc_ref = self._clean_tf_ref(props.get("vpc_name") or props.get("vpc_id"), "aws_vpc", default_name=vpcs[0]['name'] if vpcs else 'main_vpc', mapped_resources=mapped_resources)
                blocks.append(f"""resource "aws_route_table" "{name}" {{
  vpc_id = {vpc_ref}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_route":
                rt_ref = self._clean_tf_ref(props.get("route_table_name") or props.get("route_table_id"), "aws_route_table", default_name="public", mapped_resources=mapped_resources)
                dest_cidr = props.get("destination_cidr_block", "0.0.0.0/0")
                if props.get("nat_gateway_name") or props.get("nat_gateway_id"):
                    nat_ref = self._clean_tf_ref(props.get("nat_gateway_name") or props.get("nat_gateway_id"), "aws_nat_gateway", default_name="nat_gw", mapped_resources=mapped_resources)
                    target_gw_line = f"  nat_gateway_id         = {nat_ref}"
                else:
                    igw_ref = self._clean_tf_ref(props.get("gateway_name") or props.get("gateway_id"), "aws_internet_gateway", default_name="igw", mapped_resources=mapped_resources)
                    target_gw_line = f"  gateway_id             = {igw_ref}"

                blocks.append(f"""resource "aws_route" "{name}" {{
  route_table_id         = {rt_ref}
  destination_cidr_block = "{dest_cidr}"
{target_gw_line}
}}
""")

            elif tf_type == "aws_route_table_association":
                sub_ref = self._clean_tf_ref(props.get("subnet_name") or props.get("subnet_id"), "aws_subnet", mapped_resources=mapped_resources)
                rt_ref = self._clean_tf_ref(props.get("route_table_name") or props.get("route_table_id"), "aws_route_table", mapped_resources=mapped_resources)
                blocks.append(f"""resource "aws_route_table_association" "{name}" {{
  subnet_id      = {sub_ref}
  route_table_id = {rt_ref}
}}
""")

            elif tf_type == "aws_s3_bucket":
                raw_bname = props.get("bucket_name") or props.get("name") or name
                bucket_name = str(raw_bname).lower().replace("_", "-")
                is_website = bool(
                    props.get("website") is True
                    or props.get("static_site") is True
                    or res.get("universal_type") in ["static_site", "website_hosting"]
                    or "website" in name.lower()
                    or "site" in name.lower()
                )
                bucket_block = f"""resource "aws_s3_bucket" "{name}" {{
  bucket        = "{bucket_name}"
  force_destroy = true

  tags = {{
    Name      = "{bucket_name}"
    ManagedBy = "Vellum"
  }}
}}
"""
                has_explicit_website_cfg = any(
                    r["tf_type"] == "aws_s3_bucket_website_configuration" and (r.get("properties", {}).get("bucket_name") == name or name in r.get("name", ""))
                    for r in mapped_resources
                )
                if is_website and not has_explicit_website_cfg:
                    idx_doc = props.get("index_document", "index.html")
                    err_doc = props.get("error_document", "error.html")
                    bucket_block += f"""
resource "aws_s3_bucket_website_configuration" "{name}_website" {{
  bucket = aws_s3_bucket.{name}.id

  index_document {{
    suffix = "{idx_doc}"
  }}

  error_document {{
    key = "{err_doc}"
  }}
}}

resource "aws_s3_bucket_public_access_block" "{name}_pab" {{
  bucket = aws_s3_bucket.{name}.id

  block_public_acls       = true
  block_public_policy     = false
  ignore_public_acls      = true
  restrict_public_buckets = false
}}

resource "aws_s3_bucket_policy" "{name}_public_read" {{
  bucket     = aws_s3_bucket.{name}.id
  depends_on = [aws_s3_bucket_public_access_block.{name}_pab]

  policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [
      {{
        Sid       = "PublicReadGetObject"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${{aws_s3_bucket.{name}.arn}}/*"
      }}
    ]
  }})
}}
"""
                blocks.append(bucket_block)

            elif tf_type == "aws_s3_bucket_versioning":
                b_ref = self._clean_tf_ref(props.get("bucket_name") or props.get("bucket") or props.get("bucket_id"), "aws_s3_bucket", default_name="main", mapped_resources=mapped_resources)
                status = props.get("status", "Enabled")
                blocks.append(f"""resource "aws_s3_bucket_versioning" "{name}" {{
  bucket = {b_ref}
  versioning_configuration {{
    status = "{status}"
  }}
}}
""")

            elif tf_type == "aws_s3_bucket_server_side_encryption_configuration":
                b_ref = self._clean_tf_ref(props.get("bucket_name") or props.get("bucket") or props.get("bucket_id"), "aws_s3_bucket", default_name="main", mapped_resources=mapped_resources)
                sse_algo = props.get("sse_algorithm", "AES256")
                blocks.append(f"""resource "aws_s3_bucket_server_side_encryption_configuration" "{name}" {{
  bucket = {b_ref}

  rule {{
    apply_server_side_encryption_by_default {{
      sse_algorithm = "{sse_algo}"
    }}
  }}
}}
""")

            elif tf_type == "aws_s3_bucket_public_access_block":
                b_ref = self._clean_tf_ref(props.get("bucket_name") or props.get("bucket") or props.get("bucket_id"), "aws_s3_bucket", default_name="main", mapped_resources=mapped_resources)
                blocks.append(f"""resource "aws_s3_bucket_public_access_block" "{name}" {{
  bucket = {b_ref}

  block_public_acls       = {str(props.get('block_public_acls', True)).lower()}
  block_public_policy     = {str(props.get('block_public_policy', True)).lower()}
  ignore_public_acls      = {str(props.get('ignore_public_acls', True)).lower()}
  restrict_public_buckets = {str(props.get('restrict_public_buckets', True)).lower()}
}}
""")

            elif tf_type == "aws_security_group":
                vpc_ref = self._clean_tf_ref(props.get("vpc_name") or props.get("vpc_id"), "aws_vpc", default_name=vpcs[0]['name'] if vpcs else 'main_vpc', mapped_resources=mapped_resources)
                desc = props.get("description", "Vellum Managed Security Group")
                ports = props.get("ingress_ports", [5432])
                cidrs = props.get("cidr_blocks", ["10.0.0.0/16"])
                cidrs_hcl = "[" + ", ".join(f'"{c}"' for c in cidrs) + "]"

                ingress_rules = "\n".join([f"""  ingress {{
    from_port   = {p}
    to_port     = {p}
    protocol    = "tcp"
    cidr_blocks = {cidrs_hcl}
  }}""" for p in ports])

                blocks.append(f"""resource "aws_security_group" "{name}" {{
  name        = "{name}"
  description = "{desc}"
  vpc_id      = {vpc_ref}

{ingress_rules}

  egress {{
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_db_instance":
                engine = props.get("engine", "postgres")
                engine_ver = props.get("engine_version", "15" if "postgres" in str(engine).lower() else "8.0")
                instance_class = props.get("instance_class", "db.t3.micro")
                db_name = props.get("database_name", "app_db")
                username = props.get("username", "vellum_admin")
                storage = props.get("allocated_storage", 20)

                db_sub_groups = [r for r in mapped_resources if r["tf_type"] == "aws_db_subnet_group"]
                subnet_group_line = ""
                if db_sub_groups:
                    subnet_group_line = f'\n  db_subnet_group_name   = aws_db_subnet_group.{db_sub_groups[0]["name"]}.name'
                elif props.get("db_subnet_group_name"):
                    subnet_group_line = f'\n  db_subnet_group_name   = "{props["db_subnet_group_name"]}"'

                blocks.append(f"""resource "aws_db_instance" "{name}" {{
  identifier             = "{name.replace('_', '-')}"
  engine                 = "{engine}"
  engine_version         = "{engine_ver}"
  instance_class         = "{instance_class}"
  allocated_storage      = {storage}
  db_name                = "{db_name}"
  username               = "{username}"
  password               = "dev_password_only"{subnet_group_line}
  skip_final_snapshot    = true
  publicly_accessible    = false

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_db_subnet_group":
                sub_names = props.get("subnet_names") or props.get("subnet_ids")
                if not sub_names:
                    all_subnets = [r["name"] for r in mapped_resources if r["tf_type"] == "aws_subnet"]
                    sub_names = all_subnets if all_subnets else ["public_subnet_1"]

                clean_refs = [self._clean_tf_ref(s, "aws_subnet", mapped_resources=mapped_resources) for s in sub_names]
                subnet_refs = ", ".join(clean_refs)

                blocks.append(f"""resource "aws_db_subnet_group" "{name}" {{
  name        = "{name.replace('_', '-')}"
  description = "Database Subnet Group for {name}"
  subnet_ids  = [{subnet_refs}]

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type in ["aws_elasticache_cluster", "aws_elasticache_replication_group"]:
                engine = props.get("engine", "redis")
                node_type = props.get("node_type", "cache.t3.micro")
                num_nodes = props.get("num_cache_nodes", 1)
                port = props.get("port", 6379 if engine == "redis" else 11211)
                param_group = props.get("parameter_group_name", "default.redis7" if engine == "redis" else "default.memcached1.6")
                blocks.append(f"""resource "aws_elasticache_cluster" "{name}" {{
  cluster_id           = "{name.replace('_', '-')[:40]}"
  engine               = "{engine}"
  node_type            = "{node_type}"
  num_cache_nodes      = {num_nodes}
  parameter_group_name = "{param_group}"
  port                 = {port}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_elasticache_subnet_group":
                sub_names = props.get("subnet_names") or props.get("subnet_ids") or [r["name"] for r in mapped_resources if r["tf_type"] == "aws_subnet"]
                clean_refs = [self._clean_tf_ref(s, "aws_subnet", mapped_resources=mapped_resources) for s in sub_names]
                subnet_refs = ", ".join(clean_refs)
                blocks.append(f"""resource "aws_elasticache_subnet_group" "{name}" {{
  name       = "{name.replace('_', '-')}"
  subnet_ids = [{subnet_refs}]

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_sqs_queue":
                queue_name = props.get("queue_name") or props.get("name") or name.replace("_", "-")
                blocks.append(f"""resource "aws_sqs_queue" "{name}" {{
  name                      = "{queue_name}"
  delay_seconds             = {props.get('delay_seconds', 0)}
  max_message_size          = {props.get('max_message_size', 262144)}
  message_retention_seconds = {props.get('message_retention_seconds', 345600)}

  tags = {{
    Name      = "{queue_name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_sns_topic":
                topic_name = props.get("topic_name") or props.get("name") or name.replace("_", "-")
                blocks.append(f"""resource "aws_sns_topic" "{name}" {{
  name = "{topic_name}"

  tags = {{
    Name      = "{topic_name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_dynamodb_table":
                table_name = props.get("table_name") or props.get("name") or name.replace("_", "-")
                hash_key = props.get("hash_key", "id")
                blocks.append(f"""resource "aws_dynamodb_table" "{name}" {{
  name         = "{table_name}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "{hash_key}"

  attribute {{
    name = "{hash_key}"
    type = "S"
  }}

  tags = {{
    Name      = "{table_name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_secretsmanager_secret":
                secret_name = props.get("secret_name") or props.get("name") or name.replace("_", "-")
                blocks.append(f"""resource "aws_secretsmanager_secret" "{name}" {{
  name = "{secret_name}"

  tags = {{
    Name      = "{secret_name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_iam_role":
                role_name = props.get("role_name") or props.get("name") or name.replace("_", "-")
                blocks.append(f"""resource "aws_iam_role" "{name}" {{
  name = "{role_name}"

  assume_role_policy = jsonencode({{
    Version = "2012-10-17"
    Statement = [
      {{
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {{
          Service = "ec2.amazonaws.com"
        }}
      }}
    ]
  }})

  tags = {{
    Name      = "{role_name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_instance":
                ami = props.get("ami", "ami-0c55b159cbfafe1f0")
                instance_type = props.get("instance_type", "t3.micro")
                blocks.append(f"""resource "aws_instance" "{name}" {{
  ami           = "{ami}"
  instance_type = "{instance_type}"

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_eip":
                blocks.append(f"""resource "aws_eip" "{name}" {{
  domain = "vpc"

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_nat_gateway":
                alloc_ref = self._clean_tf_ref(
                    props.get("allocation_id") or props.get("eip_name"),
                    "aws_eip",
                    default_name=f"{name}_eip",
                    mapped_resources=mapped_resources,
                )
                sub_ref = self._clean_tf_ref(
                    props.get("subnet_id") or props.get("subnet_name"),
                    "aws_subnet",
                    default_name="main",
                    mapped_resources=mapped_resources,
                    filter_fn=lambda r: bool(r.get("properties", {}).get("map_public_ip_on_launch") or "public" in r.get("name", "").lower()),
                )

                blocks.append(f"""resource "aws_nat_gateway" "{name}" {{
  allocation_id = {alloc_ref}
  subnet_id     = {sub_ref}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            else:
                # Dynamic generic AWS resource serializer (no resource dropped)
                clean_tf_type = tf_type if tf_type.startswith("aws_") else f"aws_{tf_type}"
                attr_lines = []
                for k, v in props.items():
                    if k.startswith("_") or k in ["vpc_name"]:
                        continue
                    if isinstance(v, bool):
                        attr_lines.append(f"  {k} = {str(v).lower()}")
                    elif isinstance(v, (int, float)):
                        attr_lines.append(f"  {k} = {v}")
                    elif isinstance(v, str):
                        attr_lines.append(f'  {k} = "{v}"')
                    elif isinstance(v, list):
                        list_items = ", ".join(f'"{item}"' if isinstance(item, str) else str(item) for item in v)
                        attr_lines.append(f"  {k} = [{list_items}]")
                attrs_body = "\n".join(attr_lines) if attr_lines else f'  # properties configured\n  name = "{name}"'
                blocks.append(f"""resource "{clean_tf_type}" "{name}" {{
{attrs_body}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

        # Add Outputs
        outputs = []
        for res in mapped_resources:
            tf_type = res["tf_type"]
            name = res["name"]
            if tf_type == "aws_vpc":
                outputs.append(f'output "{name}_id" {{\n  value = aws_vpc.{name}.id\n}}')
            elif tf_type == "aws_subnet":
                outputs.append(f'output "{name}_id" {{\n  value = aws_subnet.{name}.id\n}}')
            elif tf_type == "aws_s3_bucket":
                outputs.append(f'output "{name}_bucket" {{\n  value = aws_s3_bucket.{name}.bucket\n}}')
                is_website = bool(
                    res.get("properties", {}).get("website") is True
                    or res.get("properties", {}).get("static_site") is True
                    or res.get("universal_type") in ["static_site", "website_hosting"]
                    or "website" in name.lower()
                    or "site" in name.lower()
                )
                if is_website:
                    outputs.append(f'output "{name}_website_endpoint" {{\n  value = aws_s3_bucket_website_configuration.{name}_website.website_endpoint\n}}')
            elif tf_type == "aws_internet_gateway":
                outputs.append(f'output "{name}_id" {{\n  value = aws_internet_gateway.{name}.id\n}}')
            elif tf_type == "aws_route_table":
                outputs.append(f'output "{name}_id" {{\n  value = aws_route_table.{name}.id\n}}')
            elif tf_type == "aws_db_instance":
                outputs.append(f'output "{name}_endpoint" {{\n  value = aws_db_instance.{name}.endpoint\n}}')
            elif tf_type == "aws_elasticache_cluster":
                outputs.append(f'output "{name}_cache_nodes" {{\n  value = aws_elasticache_cluster.{name}.cache_nodes\n}}')
            elif tf_type == "aws_sqs_queue":
                outputs.append(f'output "{name}_url" {{\n  value = aws_sqs_queue.{name}.url\n}}')
            elif tf_type == "aws_sns_topic":
                outputs.append(f'output "{name}_arn" {{\n  value = aws_sns_topic.{name}.arn\n}}')
            elif tf_type == "aws_dynamodb_table":
                outputs.append(f'output "{name}_name" {{\n  value = aws_dynamodb_table.{name}.name\n}}')
            elif tf_type == "aws_secretsmanager_secret":
                outputs.append(f'output "{name}_arn" {{\n  value = aws_secretsmanager_secret.{name}.arn\n}}')
            elif tf_type == "aws_nat_gateway":
                outputs.append(f'output "{name}_id" {{\n  value = aws_nat_gateway.{name}.id\n}}')
            elif tf_type == "aws_eip":
                outputs.append(f'output "{name}_public_ip" {{\n  value = aws_eip.{name}.public_ip\n}}')

        if outputs:
            blocks.append("\n# Outputs\n" + "\n".join(outputs))

        hcl_text = "\n".join(blocks)
        # Sanitization pass: eliminate any malformed interpolations like aws_foo.${bar.id}.id or aws_foo.${bar}
        hcl_text = re.sub(
            r'([a-zA-Z0-9_]+)\.\$\{([a-zA-Z0-9_]+)(?:\.id)?\}\.id',
            r'\1.\2.id',
            hcl_text,
        )
        hcl_text = re.sub(
            r'([a-zA-Z0-9_]+)\.\$\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_]+)\}',
            r'\1.\2.\3',
            hcl_text,
        )
        hcl_text = re.sub(
            r'([a-zA-Z0-9_]+)\.\$\{([a-zA-Z0-9_]+)\}',
            r'\1.\2',
            hcl_text,
        )
        return hcl_text
