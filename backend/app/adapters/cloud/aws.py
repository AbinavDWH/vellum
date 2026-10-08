import re
from typing import Dict, Any, List, Optional
from app.adapters.cloud.base import CloudProviderAdapter
from app.config import settings


class AWSAdapter(CloudProviderAdapter):
    """AWS implementation with LocalStack support."""

    MAPPING = {
        # Networking
        "virtual_network": "aws_vpc",
        "vpc": "aws_vpc",
        "network": "aws_vpc",
        "subnet": "aws_subnet",
        "security_group": "aws_security_group",
        "security_rule": "aws_security_group",
        "sg": "aws_security_group",
        "internet_gateway": "aws_internet_gateway",
        "nat_gateway": "aws_nat_gateway",
        "route_table": "aws_route_table",
        "route": "aws_route",
        "aws_route": "aws_route",
        "route_table_association": "aws_route_table_association",
        "aws_route_table_association": "aws_route_table_association",
        "public_subnet": "aws_subnet",
        "private_subnet": "aws_subnet",

        # Databases
        "managed_database": "aws_db_instance",
        "database": "aws_db_instance",
        "rds": "aws_db_instance",
        "rds_instance": "aws_db_instance",
        "db_instance": "aws_db_instance",
        "db_subnet_group": "aws_db_subnet_group",
        "rds_subnet_group": "aws_db_subnet_group",
        "subnet_group": "aws_db_subnet_group",

        # Caching
        "elasticache": "aws_elasticache_cluster",
        "elasticache_cluster": "aws_elasticache_cluster",
        "cache": "aws_elasticache_cluster",
        "cache_cluster": "aws_elasticache_cluster",
        "redis": "aws_elasticache_cluster",
        "redis_cluster": "aws_elasticache_replication_group",
        "elasticache_replication_group": "aws_elasticache_replication_group",
        "elasticache_subnet_group": "aws_elasticache_subnet_group",

        # Storage
        "object_storage": "aws_s3_bucket",
        "storage_bucket": "aws_s3_bucket",
        "s3_bucket": "aws_s3_bucket",
        "bucket": "aws_s3_bucket",
        "s3": "aws_s3_bucket",
        "static_site": "aws_s3_bucket",
        "website_hosting": "aws_s3_bucket",
        "website": "aws_s3_bucket",

        # Compute
        "compute_instance": "aws_instance",
        "ec2": "aws_instance",
        "instance": "aws_instance",
        "server": "aws_instance",

        # Messaging & NoSQL
        "sqs": "aws_sqs_queue",
        "sqs_queue": "aws_sqs_queue",
        "queue": "aws_sqs_queue",
        "sns": "aws_sns_topic",
        "sns_topic": "aws_sns_topic",
        "topic": "aws_sns_topic",
        "dynamodb": "aws_dynamodb_table",
        "dynamodb_table": "aws_dynamodb_table",

        # Security & Secrets & IAM
        "secret": "aws_secretsmanager_secret",
        "secretsmanager": "aws_secretsmanager_secret",
        "secrets_manager": "aws_secretsmanager_secret",
        "iam_role": "aws_iam_role",
        "role": "aws_iam_role",
        "lambda": "aws_lambda_function",
        "lambda_function": "aws_lambda_function",
    }

    def get_provider_name(self) -> str:
        return "aws"

    def get_local_endpoint(self) -> str:
        return settings.LOCALSTACK_URL

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

            if res_type.startswith("aws_"):
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
        environment: str = "local",
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
        localstack_url = self.get_local_endpoint()
        raw_region = region or settings.LOCALSTACK_REGION or "us-east-1"
        target_region = re.sub(r"^([a-z]{2}-[a-z]+-\d+)[a-z]$", r"\1", raw_region)
        is_local = (environment == "local")
        
        provider_block = f"""# ========================================================
# Generated by Vellum - Autonomous Infrastructure Designer
# Provider: AWS ({'LocalStack Simulation' if is_local else 'Cloud Production'})
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
"""
        if is_local:
            provider_block += f"""
provider "aws" {{
  region                      = "{target_region}"
  access_key                  = "test"
  secret_key                  = "test"
  s3_use_path_style           = true
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {{
    s3             = "{localstack_url}"
    ec2            = "{localstack_url}"
    rds            = "{localstack_url}"
    iam            = "{localstack_url}"
    sts            = "{localstack_url}"
    cloudwatch     = "{localstack_url}"
  }}
}}
"""
        else:
            # Real AWS (Production / Staging) - uses standard AWS authentication without dummy keys or endpoint overrides
            provider_block += f"""
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
                az = props.get("availability_zone", f"{settings.LOCALSTACK_REGION}a")
                vpc_ref = f"aws_vpc.{props.get('vpc_name', vpcs[0]['name'] if vpcs else 'main_vpc')}.id"
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
                vpc_ref = f"aws_vpc.{props.get('vpc_name', vpcs[0]['name'] if vpcs else 'main_vpc')}.id"
                blocks.append(f"""resource "aws_internet_gateway" "{name}" {{
  vpc_id = {vpc_ref}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_route_table":
                vpc_ref = f"aws_vpc.{props.get('vpc_name', vpcs[0]['name'] if vpcs else 'main_vpc')}.id"
                blocks.append(f"""resource "aws_route_table" "{name}" {{
  vpc_id = {vpc_ref}

  tags = {{
    Name      = "{name}"
    ManagedBy = "Vellum"
  }}
}}
""")

            elif tf_type == "aws_route":
                rt_name = props.get("route_table_name")
                rt_ref = f"aws_route_table.{rt_name}.id" if rt_name else props.get("route_table_id", "aws_route_table.public.id")
                igw_name = props.get("gateway_name")
                igw_ref = f"aws_internet_gateway.{igw_name}.id" if igw_name else props.get("gateway_id", "aws_internet_gateway.igw.id")
                dest_cidr = props.get("destination_cidr_block", "0.0.0.0/0")
                blocks.append(f"""resource "aws_route" "{name}" {{
  route_table_id         = {rt_ref}
  destination_cidr_block = "{dest_cidr}"
  gateway_id             = {igw_ref}
}}
""")

            elif tf_type == "aws_route_table_association":
                sub_name = props.get("subnet_name")
                sub_ref = f"aws_subnet.{sub_name}.id" if sub_name else props.get("subnet_id")
                rt_name = props.get("route_table_name")
                rt_ref = f"aws_route_table.{rt_name}.id" if rt_name else props.get("route_table_id")
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

            elif tf_type == "aws_security_group":
                vpc_ref = f"aws_vpc.{props.get('vpc_name', vpcs[0]['name'] if vpcs else 'main_vpc')}.id"
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

                clean_refs = []
                for s in sub_names:
                    s_str = str(s).replace("${", "").replace("}", "").replace(".id", "").replace("aws_subnet.", "").strip()
                    if s_str.startswith("subnet-"):
                        clean_refs.append(f'"{s_str}"')
                    else:
                        clean_refs.append(f"aws_subnet.{s_str}.id")
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
                subnet_refs = ", ".join([f"aws_subnet.{s}.id" if not str(s).startswith("subnet-") else f'"{s}"' for s in sub_names])
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

        if outputs:
            blocks.append("\n# Outputs\n" + "\n".join(outputs))

        return "\n".join(blocks)
