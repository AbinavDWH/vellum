# AWS RDS Database Terraform Resource Specification

## Overview
Amazon Relational Database Service (RDS) provides managed relational databases.
- `aws_db_instance`: Managed database instance (Postgres, MySQL, MariaDB, etc.).
- `aws_db_subnet_group`: Subnet grouping spanning at least 2 distinct Availability Zones.

## Resource: aws_db_instance

### Required Arguments
- `instance_class` (Required string): The instance type of the RDS instance (e.g., `"db.t3.micro"`, `"db.t4g.micro"`, `"db.r6g.large"`).
- `engine` (Required string): Database engine name (`"postgres"`, `"mysql"`, `"mariadb"`).

### Crucial Arguments & Common Hallucination Traps
- `allocated_storage` (Optional/Required number): Storage in gigabytes (e.g., `20`). Required unless using Aurora.
- `max_allocated_storage` (Optional number): Enables storage autoscaling upper limit (e.g., `100`).
- `storage_type` (Optional string, default `"gp2"`, recommended `"gp3"`): Valid values are `"standard"`, `"gp2"`, `"gp3"`, `"io1"`, `"io2"`.
- `storage_throughput` (Optional number): **WARNING**: `storage_throughput` is ONLY supported when `storage_type = "gp3"` with `allocated_storage >= 400`, or on `io1`/`io2`. Specifying `storage_throughput` with `storage_type = "gp2"` causes Terraform apply to fail with `InvalidParameterCombination`.
- `iops` (Optional number): Supported on `gp3` (allocated_storage >= 400) and `io1`/`io2`.
- `db_name` (Optional string): Name of initial database created upon launch.
- `username` (Optional string): Master database username (e.g., `"vellum_admin"`).
- `password` (Optional string): Master password. Must not be plaintext in git repos.
- `db_subnet_group_name` (Optional string): Name of `aws_db_subnet_group`. Required when deploying inside a VPC.
- `vpc_security_group_ids` (Optional list of string): Security group IDs associated with the database.
- `storage_encrypted` (Optional bool, default `true`): Specifies whether the DB instance is encrypted.
- `kms_key_id` (Optional string): KMS ARN for storage encryption.
- `skip_final_snapshot` (Optional bool, default `false`, test default `true`): Determines whether a final DB snapshot is created before the DB instance is deleted.
- `publicly_accessible` (Optional bool, default `false`): Must remain `false` for compliance.

### Resource: aws_db_subnet_group
- `name` (Optional/Required string): Subnet group name.
- `subnet_ids` (Required list of string): Must span at least TWO distinct Availability Zones (e.g., one subnet in `us-east-1a` and one in `us-east-1b`).

### HCL Example: Production PostgreSQL Instance
```hcl
resource "aws_db_subnet_group" "db_subnets" {
  name       = "vellum-db-subnet-group"
  subnet_ids = [aws_subnet.private_1.id, aws_subnet.private_2.id]

  tags = {
    Name = "vellum-db-subnet-group"
  }
}

resource "aws_db_instance" "database" {
  identifier             = "vellum-prod-postgres"
  engine                 = "postgres"
  engine_version         = "15.4"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  storage_type           = "gp3"
  storage_encrypted      = true
  db_name                = "vellum"
  username               = "vellum_admin"
  password               = "ChangeMeSecurePassword123!"
  db_subnet_group_name   = aws_db_subnet_group.db_subnets.name
  vpc_security_group_ids = [aws_security_group.db_sg.id]
  publicly_accessible    = false
  skip_final_snapshot    = true

  tags = {
    Environment = "production"
    ManagedBy   = "vellum"
  }
}
```

## Security Best Practices (CIS Benchmark Grounding)
1. **Always Set `storage_encrypted = true`**: Unencrypted databases violate CIS AWS Benchmark 2.3.1.
2. **Never Set `publicly_accessible = true`**: RDS databases must never be publicly addressable.
3. **Database Subnet Group Required**: Placing RDS in a VPC without a multi-AZ `aws_db_subnet_group` will fail execution.
