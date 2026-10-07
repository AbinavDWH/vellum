from typing import List, Dict, Any, Tuple
from app.schemas.ir import UniversalIR


class SecurityValidator:
    """Security rules auditor enforcing cloud security benchmarks (CIS, AWS Best Practices)."""

    @classmethod
    def audit(cls, ir: UniversalIR) -> List[Dict[str, Any]]:
        findings: List[Dict[str, Any]] = []

        if ir.cloud:
            for res in ir.cloud.resources:
                # Rule 1: No open ports / database ingress to 0.0.0.0/0
                if res.type == "security_rule":
                    cidr_blocks = res.properties.get("cidr_blocks", [])
                    ports = res.properties.get("ingress_ports", [])
                    is_db_port = any(p in [5432, 3306, 27017, 6379, 1433, 27018] for p in ports)
                    is_ssh_port = 22 in ports

                    if "0.0.0.0/0" in cidr_blocks:
                        if is_db_port:
                            findings.append({
                                "rule_id": "SEC-001",
                                "severity": "CRITICAL",
                                "resource": res.name,
                                "message": f"Security group '{res.name}' opens database port to the public Internet (0.0.0.0/0).",
                                "remediation": "Restrict CIDR to internal VPC CIDR block (e.g., 10.0.0.0/16)."
                            })
                        if is_ssh_port:
                            findings.append({
                                "rule_id": "SEC-005",
                                "severity": "CRITICAL",
                                "resource": res.name,
                                "message": f"Security group '{res.name}' opens SSH port (22) to the public Internet (0.0.0.0/0).",
                                "remediation": "Restrict SSH access to specific bastion host or management CIDR."
                            })
                        if not is_db_port and not is_ssh_port and ports:
                            findings.append({
                                "rule_id": "SEC-006",
                                "severity": "HIGH",
                                "resource": res.name,
                                "message": f"Security group '{res.name}' allows unrestricted ingress on ports {ports} from 0.0.0.0/0.",
                                "remediation": "Restrict CIDR to necessary subnets or specific IP ranges."
                            })


                # Rule 2: S3 bucket public access & encryption
                if res.type in ["object_storage", "storage_bucket", "s3_bucket", "static_site", "website_hosting"]:
                    is_web = bool(
                        res.properties.get("website") is True
                        or res.properties.get("static_site") is True
                        or res.type in ["static_site", "website_hosting"]
                        or "website" in res.name.lower()
                    )
                    acl = res.properties.get("acl", "private")
                    is_public = acl in ["public-read", "public-read-write"] or res.properties.get("public") is True

                    if is_public or is_web:
                        if is_web:
                            findings.append({
                                "rule_id": "SEC-002-WEB",
                                "severity": "LOW",
                                "resource": res.name,
                                "message": "This bucket will be publicly readable (Static Website Hosting enabled).",
                                "warning_chip": "This bucket will be publicly readable",
                                "remediation": "Static website hosting serves files publicly over HTTP/HTTPS.",
                            })
                        else:
                            findings.append({
                                "rule_id": "SEC-002",
                                "severity": "CRITICAL",
                                "resource": res.name,
                                "message": f"S3 Bucket '{res.name}' has public ACL ('{acl}') configured without website hosting. Public-read is allowed ONLY for website-flagged buckets.",
                                "remediation": "Use private ACL and configure explicit CloudFront or VPC endpoint access, or flag bucket with website: true."
                            })

                    # Unencrypted S3
                    encryption_enabled = res.properties.get("server_side_encryption", res.properties.get("encryption_enabled", True))
                    if encryption_enabled is False:
                        findings.append({
                            "rule_id": "SEC-007",
                            "severity": "HIGH",
                            "resource": res.name,
                            "message": f"S3 Bucket '{res.name}' has server-side encryption disabled.",
                            "remediation": "Enable AES256 or AWS KMS default server-side encryption."
                        })

                # Rule 3: Database encryption, public accessibility & credentials
                if res.type == "managed_database":
                    # Public RDS check
                    if res.properties.get("publicly_accessible") is True:
                        findings.append({
                            "rule_id": "SEC-008",
                            "severity": "CRITICAL",
                            "resource": res.name,
                            "message": f"Database '{res.name}' has publicly_accessible=true enabled.",
                            "remediation": "Deploy database in private subnets with publicly_accessible=false."
                        })

                    storage_encrypted = res.properties.get("storage_encrypted", True)
                    if not storage_encrypted:
                        findings.append({
                            "rule_id": "SEC-003",
                            "severity": "HIGH",
                            "resource": res.name,
                            "message": f"Database '{res.name}' does not have storage encryption enabled.",
                            "remediation": "Enable storage_encrypted = true."
                        })

                    # Credential check
                    if "password" in res.properties and res.properties["password"] not in ["", None]:
                        findings.append({
                            "rule_id": "SEC-004",
                            "severity": "HIGH",
                            "resource": res.name,
                            "message": f"Database '{res.name}' has plain text password in resource properties.",
                            "remediation": "Use Credential Manager or AWS Secrets Manager variable."
                        })

        return findings

    @classmethod
    def blocks_execution(cls, findings: List[Dict[str, Any]]) -> Tuple[bool, List[str]]:
        """Return True and error messages if any CRITICAL security findings violate policy."""
        blocking = [f["message"] for f in findings if f.get("severity") == "CRITICAL"]
        return len(blocking) > 0, blocking

