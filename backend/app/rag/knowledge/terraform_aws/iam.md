# AWS IAM Roles and Policies Terraform Resource Specification

## Overview
AWS Identity and Access Management (IAM) manages secure access to AWS services:
- `aws_iam_role`: Identity with permission policies that determine what the identity can and cannot do in AWS.
- `aws_iam_policy`: Managed policy defining granular permissions via JSON.
- `aws_iam_role_policy_attachment`: Attaches a managed policy to an IAM role.

## Resource: aws_iam_role

### Required Arguments
- `assume_role_policy` (Required string): The policy that grants an entity permission to assume the role (JSON formatted).

### Optional Arguments
- `name` (Optional string): Name of the role.
- `description` (Optional string): Role description.
- `tags` (Optional map of string): Resource tags.

## Resource: aws_iam_policy

### Required Arguments
- `policy` (Required string): The policy document in valid JSON format.

### Optional Arguments
- `name` (Optional string): Name of the policy.
- `description` (Optional string): Description of the policy.

### HCL Example: Least-Privilege Lambda / Service Role
```hcl
resource "aws_iam_role" "app_execution_role" {
  name = "vellum-service-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action    = "sts:AssumeRole"
        Effect    = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Environment = "production"
  }
}

resource "aws_iam_policy" "s3_read_policy" {
  name        = "vellum-s3-read-policy"
  description = "Grants read access to the vellum artifacts bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::vellum-secure-artifacts-bucket",
          "arn:aws:s3:::vellum-secure-artifacts-bucket/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "attach_s3_read" {
  role       = aws_iam_role.app_execution_role.name
  policy_arn = aws_iam_policy.s3_read_policy.arn
}
```

## Security Best Practices (CIS Benchmark Grounding)
1. **Never Grant Full Admin (`*` on `*`)**: Policies with `Action: "*"` and `Resource: "*"` violate CIS Benchmark 1.16. Always scope Actions to exact APIs and Resources to target ARNs.
2. **Use Role Delegation Over Static Keys**: Prefer IAM Roles for compute resources rather than hardcoded access keys and secret keys.
