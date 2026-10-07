import time
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class GoldenTestCase(BaseModel):
    query: str
    expected_domain: str
    expected_resource_types: List[str]
    expected_keywords: List[str]


# Authoritative Golden Evaluation Dataset covering Terraform specs, CIS benchmarks, and remediations
GOLDEN_DATASET: List[GoldenTestCase] = [
    GoldenTestCase(
        query="Does aws_db_instance support storage_throughput?",
        expected_domain="terraform_aws",
        expected_resource_types=["aws_db_instance"],
        expected_keywords=["storage_throughput", "gp3", "allocated_storage"],
    ),
    GoldenTestCase(
        query="How to configure S3 bucket server side encryption for CIS compliance?",
        expected_domain="cis_benchmarks",
        expected_resource_types=["aws_s3_bucket"],
        expected_keywords=["encryption", "aes256", "aws:kms"],
    ),
    GoldenTestCase(
        query="Is opening SSH port 22 to 0.0.0.0/0 allowed by security policies?",
        expected_domain="cis_benchmarks",
        expected_resource_types=["aws_security_group"],
        expected_keywords=["22", "ssh", "0.0.0.0/0", "violate"],
    ),
    GoldenTestCase(
        query="What are the requirements for an RDS DB subnet group?",
        expected_domain="terraform_aws",
        expected_resource_types=["aws_db_instance"],
        expected_keywords=["subnet", "availability zone", "multi-az"],
    ),
    GoldenTestCase(
        query="How to prevent public access on an S3 bucket?",
        expected_domain="terraform_aws",
        expected_resource_types=["aws_s3_bucket"],
        expected_keywords=["block_public_acls", "block_public_policy", "public_access_block"],
    ),
    GoldenTestCase(
        query="Remediate DBSubnetGroupDoesNotCoverEnoughAZs terraform error",
        expected_domain="remediations",
        expected_resource_types=[],
        expected_keywords=["availability zones", "subnet", "remediation"],
    ),
    GoldenTestCase(
        query="How to create a multi-tier VPC with public and private subnets?",
        expected_domain="terraform_aws",
        expected_resource_types=["aws_vpc"],
        expected_keywords=["cidr_block", "subnet", "internet_gateway"],
    ),
    GoldenTestCase(
        query="IAM least privilege role policy for S3 bucket access",
        expected_domain="terraform_aws",
        expected_resource_types=["aws_iam_role"],
        expected_keywords=["assume_role_policy", "least privilege", "arn"],
    ),
]


class BenchmarkResult(BaseModel):
    total_queries: int
    hit_rate: float
    mrr: float
    recall_at_5: float
    avg_latency_ms: float
    passed_ci_gate: bool
    details: List[Dict[str, Any]] = Field(default_factory=list)


class GoldenBenchmarkRunner:
    """
    Layer 8: Quantitative Evaluation Runner measuring Recall@k, MRR, and Hit Rate.
    Can be run as part of CI gates or on-demand via API.
    """

    def __init__(self, rag_service: Any):
        self.rag_service = rag_service

    def run_eval(self, top_k: int = 5) -> BenchmarkResult:
        hits = 0
        reciprocal_ranks = []
        recalls = []
        latencies = []
        details = []

        for case in GOLDEN_DATASET:
            t0 = time.time()
            results = self.rag_service.search(query=case.query, top_k=top_k)
            latency = (time.time() - t0) * 1000
            latencies.append(latency)

            matched_rank: Optional[int] = None
            found_keywords = 0

            for rank, r in enumerate(results, start=1):
                # Check domain or resource type match
                domain_match = r.domain == case.expected_domain
                res_match = any(rt in (r.resource_type or "") for rt in case.expected_resource_types)
                text_match = any(kw.lower() in (r.content + r.title).lower() for kw in case.expected_keywords)

                if (domain_match or res_match or text_match) and matched_rank is None:
                    matched_rank = rank

            if matched_rank is not None:
                hits += 1
                reciprocal_ranks.append(1.0 / matched_rank)
                recalls.append(1.0)
            else:
                reciprocal_ranks.append(0.0)
                recalls.append(0.0)

            details.append({
                "query": case.query,
                "hit": matched_rank is not None,
                "matched_rank": matched_rank,
                "top_result_title": results[0].title if results else "None",
                "latency_ms": round(latency, 2),
            })

        n = len(GOLDEN_DATASET)
        hit_rate = (hits / n) if n > 0 else 0.0
        mrr = (sum(reciprocal_ranks) / n) if n > 0 else 0.0
        recall_at_5 = (sum(recalls) / n) if n > 0 else 0.0
        avg_lat = (sum(latencies) / n) if n > 0 else 0.0

        # CI Gate: Requires Hit Rate >= 85% and MRR >= 0.70
        passed_ci = hit_rate >= 0.85 and mrr >= 0.70

        return BenchmarkResult(
            total_queries=n,
            hit_rate=round(hit_rate, 4),
            mrr=round(mrr, 4),
            recall_at_5=round(recall_at_5, 4),
            avg_latency_ms=round(avg_lat, 2),
            passed_ci_gate=passed_ci,
            details=details,
        )
