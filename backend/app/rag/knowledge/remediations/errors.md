# Terraform and Cloud Remediation Guide

## Domain: remediations
Authoritative error-to-remediation pairs for Terraform apply errors and LocalStack sandbox quirks.

---

## 1. Storage Throughput Unsupported Error
- **Error Pattern**: `Error: InvalidParameterCombination: storage_throughput is not supported for storage_type gp2` or `storage_throughput is only valid when allocated_storage is at least 400`
- **Root Cause**: The LLM hallucinated the `storage_throughput` attribute on a standard `gp2` or undersized `gp3` database instance.
- **Remediation**:
  1. Remove `storage_throughput` entirely if running standard workloads.
  2. If high throughput is required, set `storage_type = "gp3"` AND set `allocated_storage >= 400`.
  3. Or change `storage_type = "io1"` or `"io2"` with `iops = 3000`.

---

## 2. DB Subnet Group Availability Zone Coverage Error
- **Error Pattern**: `DBSubnetGroupDoesNotCoverEnoughAZs: The DB subnet group doesn't meet the requirement of having subnets in at least 2 availability zones`
- **Root Cause**: RDS instances require subnet redundancy across at least two separate AZs. Placing both subnets in `us-east-1a` fails validation.
- **Remediation**:
  1. Define two `aws_subnet` resources with distinct `availability_zone` arguments: e.g., one in `us-east-1a` and one in `us-east-1b`.
  2. Pass both subnet IDs into `aws_db_subnet_group.subnet_ids = [aws_subnet.sub1.id, aws_subnet.sub2.id]`.

---

## 3. Terraform Provider Plugin Download Timeout
- **Error Pattern**: `Command '['terraform', 'init']' timed out after 60 seconds`
- **Root Cause**: Terraform CLI attempting to download binary plugins across the public internet inside an isolated or rate-limited sandbox.
- **Remediation**:
  1. Ensure `plugin_cache_dir = "~/.terraform.d/plugin-cache"` is configured in `~/.terraformrc`.
  2. Set environment variable `TF_PLUGIN_CACHE_DIR=/home/abinav/.terraform.d/plugins`.
  3. Increase `terraform init` subprocess timeout to 120 seconds.

---

## 4. S3 Bucket Already Exists Conflict
- **Error Pattern**: `BucketAlreadyExists: The requested bucket name is not available` or `BucketAlreadyOwnedByYou`
- **Root Cause**: S3 bucket namespaces are globally unique across all AWS accounts.
- **Remediation**:
  1. Append dynamic suffixes or project prefixes to bucket names: e.g. `bucket = "vellum-app-${var.environment}-${random_id.val.hex}"`.
  2. Add `force_destroy = true` in development and sandbox environments so teardown operations can remove non-empty buckets cleanly.
