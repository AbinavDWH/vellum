# CIS AWS Foundations Benchmark Compliance Matrix

## Domain: cis_benchmarks
This knowledge base document provides authoritative CIS AWS Foundations Benchmark rules enforced across all Vellum infrastructure designs.

---

## 1. Storage & Encryption Benchmarks

### CIS 2.1.1: Ensure All S3 Buckets Employ Server-Side Encryption
- **Requirement**: All S3 buckets must have server-side encryption enabled at rest using either SSE-S3 (`AES256`) or AWS Key Management Service (`aws:kms`).
- **Terraform Enforcement**:
  Every `aws_s3_bucket` must be accompanied by an `aws_s3_bucket_server_side_encryption_configuration` resource specifying `sse_algorithm = "AES256"` or `sse_algorithm = "aws:kms"`.
- **Failure Severity**: CRITICAL. Infrastructure violating this must be blocked during validation.

### CIS 2.1.2: Ensure S3 Bucket Public Access Block is Enabled
- **Requirement**: Amazon S3 Public Access Block settings must be turned on at the bucket level.
- **Terraform Enforcement**:
  Every S3 bucket must declare an `aws_s3_bucket_public_access_block` with:
  - `block_public_acls = true`
  - `block_public_policy = true`
  - `ignore_public_acls = true`
  - `restrict_public_buckets = true`

### CIS 2.3.1: Ensure RDS Database Instances Have Encryption Enabled
- **Requirement**: RDS storage must be encrypted at rest using AWS KMS.
- **Terraform Enforcement**:
  In `aws_db_instance`, `storage_encrypted` must be explicitly set to `true`.

---

## 2. Networking & Security Group Benchmarks

### CIS 4.1: Ensure No Security Group Allows Ingress from 0.0.0.0/0 to Port 22 (SSH)
- **Requirement**: Security groups must not have inbound rules permitting traffic from `0.0.0.0/0` (any IPv4 address) or `::/0` (any IPv6 address) to TCP port 22.
- **Remediation**: In `aws_security_group`, restrict ingress `cidr_blocks` to specific management subnets or VPN gateways (e.g. `["10.0.0.0/8"]`).
- **Failure Severity**: HIGH.

### CIS 4.2: Ensure No Security Group Allows Ingress from 0.0.0.0/0 to Port 3389 (RDP)
- **Requirement**: Security groups must not allow public inbound traffic on Windows Remote Desktop Protocol (RDP) port 3389.
- **Failure Severity**: HIGH.

### CIS 4.3: Ensure Database Ports (5432, 3306) Are Not Exposed to the Internet
- **Requirement**: Database listeners (PostgreSQL port 5432, MySQL port 3306, Oracle port 1521, MSSQL port 1433) must only receive traffic from application security groups or internal VPC subnets.
- **Terraform Enforcement**:
  Never set `cidr_blocks = ["0.0.0.0/0"]` on database ports. Use `security_groups = [aws_security_group.app_sg.id]` instead.

---

## 3. Identity and Access Management Benchmarks

### CIS 1.16: Ensure IAM Policies Adhere to Least Privilege
- **Requirement**: Do not attach policies with `Action: "*"` and `Resource: "*"`. Always specify explicit actions and resource ARNs.
