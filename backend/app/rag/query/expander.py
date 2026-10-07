import re
from typing import List, Dict, Set, Optional, Tuple
from pydantic import BaseModel, Field


class ParsedQuery(BaseModel):
    original_query: str
    expanded_query: str
    sub_queries: List[str] = Field(default_factory=list)
    detected_resource_types: List[str] = Field(default_factory=list)
    target_domain: Optional[str] = None


class QueryExpander:
    """
    Layer 5: Query Understanding, Expansion & Sub-Query Decomposition.
    Features:
    - Infrastructure acronym expansion (SG -> security group, RDS -> aws_db_instance).
    - Multi-service compound query decomposition.
    - Automatic target resource type and domain inference.
    """

    ACRONYM_MAP: Dict[str, str] = {
        r"\bsg\b": "security group aws_security_group",
        r"\brds\b": "relational database aws_db_instance",
        r"\bigw\b": "internet gateway aws_internet_gateway",
        r"\brt\b": "route table aws_route_table",
        r"\baz\b": "availability zone",
        r"\biam\b": "identity access management aws_iam_role",
        r"\bpab\b": "public access block aws_s3_bucket_public_access_block",
        r"\bsse\b": "server side encryption aws_s3_bucket_server_side_encryption_configuration",
        r"\bvpc\b": "virtual private cloud aws_vpc",
        r"\bs3\b": "simple storage service aws_s3_bucket",
        r"\bkms\b": "key management service encryption",
    }

    SERVICE_PATTERNS: Dict[str, Tuple[str, str]] = {
        "s3": ("terraform_aws", "aws_s3_bucket"),
        "bucket": ("terraform_aws", "aws_s3_bucket"),
        "vpc": ("terraform_aws", "aws_vpc"),
        "subnet": ("terraform_aws", "aws_subnet"),
        "network": ("terraform_aws", "aws_vpc"),
        "security group": ("terraform_aws", "aws_security_group"),
        "firewall": ("terraform_aws", "aws_security_group"),
        "rds": ("terraform_aws", "aws_db_instance"),
        "database": ("terraform_aws", "aws_db_instance"),
        "postgres": ("terraform_aws", "aws_db_instance"),
        "mysql": ("terraform_aws", "aws_db_instance"),
        "iam": ("terraform_aws", "aws_iam_role"),
        "role": ("terraform_aws", "aws_iam_role"),
        "policy": ("terraform_aws", "aws_iam_policy"),
        "cis": ("cis_benchmarks", ""),
        "benchmark": ("cis_benchmarks", ""),
        "compliance": ("cis_benchmarks", ""),
        "error": ("remediations", ""),
        "timeout": ("remediations", ""),
        "failed": ("remediations", ""),
        "remediation": ("remediations", ""),
    }

    def expand(self, query: str) -> ParsedQuery:
        """Expand acronyms, detect resource types, and decompose compound requirements."""
        clean = query.strip()
        expanded = clean

        # 1. Expand known infrastructure acronyms
        for pattern, replacement in self.ACRONYM_MAP.items():
            if re.search(pattern, expanded, flags=re.IGNORECASE):
                expanded = re.sub(pattern, replacement, expanded, flags=re.IGNORECASE)

        # 2. Detect target domain and resource types
        detected_types: Set[str] = set()
        detected_domain: Optional[str] = None
        expanded_lower = expanded.lower()

        for keyword, (dom, res_type) in self.SERVICE_PATTERNS.items():
            if keyword in expanded_lower:
                if res_type:
                    detected_types.add(res_type)
                if not detected_domain or dom == "cis_benchmarks":
                    detected_domain = dom

        # 3. Sub-query decomposition for compound requests
        sub_queries = self._decompose(clean)

        return ParsedQuery(
            original_query=clean,
            expanded_query=expanded,
            sub_queries=sub_queries,
            detected_resource_types=sorted(list(detected_types)),
            target_domain=detected_domain,
        )

    def _decompose(self, query: str) -> List[str]:
        """Split compound multi-service queries (e.g. 'VPC with RDS and S3') into atomic sub-queries."""
        sub_queries: List[str] = []
        lower = query.lower()

        # Check for multi-service presence
        services_found = []
        if any(w in lower for w in ["s3", "bucket", "blob", "storage"]):
            services_found.append("S3 bucket storage configuration and encryption")
        if any(w in lower for w in ["vpc", "subnet", "network", "gateway", "cidr"]):
            services_found.append("VPC network subnets and route table configuration")
        if any(w in lower for w in ["rds", "database", "postgres", "mysql"]):
            services_found.append("RDS database instance storage and db subnet group")
        if any(w in lower for w in ["iam", "role", "policy", "permission"]):
            services_found.append("IAM role and policy least privilege")
        if any(w in lower for w in ["cis", "security", "encryption", "public access"]):
            services_found.append("CIS benchmark compliance encryption and access rules")

        if len(services_found) > 1:
            return services_found
        return [query]
