# AWS VPC and Networking Terraform Resource Specification

## Overview
The AWS Networking stack provides isolated virtual networks:
- `aws_vpc`: Virtual Private Cloud network space.
- `aws_subnet`: Subnets within specific Availability Zones.
- `aws_internet_gateway`: Internet egress/ingress gateway for public subnets.
- `aws_route_table` & `aws_route_table_association`: Route traffic to internet gateways or NAT.
- `aws_security_group`: Stateful firewall governing inbound and outbound traffic.

## Resource: aws_vpc

### Required Arguments
- `cidr_block` (Required string): The IPv4 CIDR block for the VPC (e.g., `"10.0.0.0/16"`, `"172.16.0.0/16"`).

### Optional Arguments
- `enable_dns_support` (Optional bool, default `true`): A boolean flag to enable/disable DNS support in the VPC.
- `enable_dns_hostnames` (Optional bool, default `false`, recommended `true`): A boolean flag to enable/disable DNS hostnames in the VPC.
- `tags` (Optional map of string): Resource tags.

## Resource: aws_subnet

### Required Arguments
- `vpc_id` (Required string): The VPC ID.
- `cidr_block` (Required string): The IPv4 CIDR block for the subnet (e.g., `"10.0.1.0/24"`).

### Optional Arguments
- `availability_zone` (Optional string): The AZ for the subnet (e.g., `"us-east-1a"`, `"us-east-1b"`).
- `map_public_ip_on_launch` (Optional bool, default `false`): Specify `true` to indicate that instances launched into the subnet should be assigned a public IP address.

## Resource: aws_security_group

### Arguments
- `name` (Optional string): Name of the security group.
- `vpc_id` (Optional string): VPC ID.
- `description` (Optional string): Security group description.
- `ingress` (Optional list/block): Inbound rules (`from_port`, `to_port`, `protocol`, `cidr_blocks`).
- `egress` (Optional list/block): Outbound rules.

### HCL Example: Production Multi-Tier VPC
```hcl
resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name        = "vellum-production-vpc"
    Environment = "production"
  }
}

resource "aws_subnet" "public_1" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.1.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = true

  tags = {
    Name = "vellum-public-subnet-1"
  }
}

resource "aws_subnet" "public_2" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.0.2.0/24"
  availability_zone       = "us-east-1b"
  map_public_ip_on_launch = true

  tags = {
    Name = "vellum-public-subnet-2"
  }
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name = "vellum-main-gw"
  }
}

resource "aws_security_group" "web_sg" {
  name        = "vellum-web-sg"
  description = "Allow HTTPS and HTTP inbound traffic"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "Allow all outbound traffic"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
```

## Security Best Practices (CIS Benchmark Grounding)
1. **Never Open Port 22 to 0.0.0.0/0**: Ingress rules for port 22 (SSH) must restrict `cidr_blocks` to specific corporate bastion CIDRs or internal VPC CIDRs. `0.0.0.0/0` on port 22 directly violates CIS AWS Benchmark 4.1.
2. **Never Open Database Ports to 0.0.0.0/0**: Ports 5432 (PostgreSQL) and 3306 (MySQL) must never accept `0.0.0.0/0`.
3. **Multi-AZ Subnets**: Always create subnets across at least 2 distinct Availability Zones for high availability and RDS multi-AZ support.
