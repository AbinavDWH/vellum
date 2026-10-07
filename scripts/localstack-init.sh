#!/bin/bash
# scripts/localstack-init.sh
# Runs automatically when LocalStack is ready

echo "🚀 Initializing LocalStack resources for Vellum..."

# Create a test S3 bucket
awslocal s3 mb s3://vellum-artifacts 2>/dev/null || true

# Create a test VPC
awslocal ec2 create-vpc --cidr-block 10.0.0.0/16 2>/dev/null || true

echo "✅ LocalStack initialization complete."
