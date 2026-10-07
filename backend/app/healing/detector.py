import re
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class DetectedError(BaseModel):
    signature: str
    error_class: str  # state_conflict, ordering, addressing, generation, transient, capacity, state, auth, quota, runtime, unknown
    message: str
    raw_excerpt: str = ""
    is_unfixable: bool = False
    remediation_class: str = "auto"  # auto, approve, halted
    default_remediation: str = ""
    max_attempts: int = 1
    diagnosis: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @property
    def details(self) -> Dict[str, Any]:
        return self.metadata

    @property
    def recommended_action(self) -> str:
        return self.default_remediation



class ErrorDetector:
    """Deterministic error signature detector for execution logs and command stderr."""

    # Unfixable error patterns (must immediately HALT)
    AUTH_PATTERNS = [
        re.compile(r'(?i)(AccessDenied|UnauthorizedOperation|403\s+Forbidden|NotAuthorized|User\s+is\s+not\s+authorized|InvalidClientTokenId|SignatureDoesNotMatch)'),
    ]

    QUOTA_PATTERNS = [
        re.compile(r'(?i)(LimitExceeded|VcpuLimitExceeded|ResourceLimitExceeded|AccountQuotaExceeded|TooManyBuckets|Max.*Exceeded|quota\s+exceeded)'),
    ]

    RUNTIME_PATTERNS = [
        re.compile(r'(?i)(Killed|Out\s+of\s+memory|OOM|apply\s+timeout|Command\s+timed\s+out|signal:\s+killed)'),
    ]

    # Fixable error patterns
    BUCKET_EXISTS_PATTERN = re.compile(
        r'(?i)(BucketAlreadyExists|BucketAlreadyOwnedByYou|creating\s+S3\s+Bucket\s+\(([^)]+)\):\s+BucketAlready)'
    )

    CIDR_OVERLAP_PATTERNS = [
        re.compile(r'(?i)(InvalidSubnet\.Range)'),
        re.compile(r'(?i)CIDR\s+address\s+([0-9./]+)\s+overlaps\s+with'),
        re.compile(r'(?i)The\s+CIDR\s+[\'"]?([0-9./]+)[\'"]?\s+conflicts\s+with'),
        re.compile(r'(?i)overlaps\s+with\s+existing\s+subnet'),
    ]

    DEPENDENCY_ORDER_PATTERNS = [
        re.compile(r'(?i)(ResourceNotFoundException|ResourceNotFound|DependencyViolation|Cannot\s+find\s+resource|does\s+not\s+exist\s+yet|Reference\s+to\s+undeclared\s+resource)'),
        re.compile(r'(?i)with\s+([a-zA-Z0-9_.]+),\s+on\s+.*:\s+resource\s+([a-zA-Z0-9_.]+)\s+has\s+not\s+been\s+created'),
    ]

    HCL_SYNTAX_PATTERNS = [
        re.compile(r'(?i)(Error:\s+Invalid\s+block\s+definition)'),
        re.compile(r'(?i)(Error:\s+Argument\s+or\s+block\s+type\s+not\s+expected)'),
        re.compile(r'(?i)(Argument\s+or\s+block\s+definition\s+required)'),
        re.compile(r'(?i)(Error:\s+Missing\s+newline\s+after\s+argument)'),
        re.compile(r'(?i)(Error:\s+Unsupported\s+block\s+type)'),
        re.compile(r'(?i)(syntax\s+error\s+in\s+.*\.tf)'),
        re.compile(r'(?i)(Error:\s+Invalid\s+attribute\s+name)'),
    ]

    SQL_SYNTAX_PATTERNS = [
        re.compile(r'(?i)(syntax\s+error\s+at\s+or\s+near)'),
        re.compile(r'(?i)(near\s+["\'][^"\']+["\']:\s+syntax\s+error)'),
        re.compile(r'(?i)(Failed\s+to\s+parse\s+SQL)'),
        re.compile(r'(?i)(relation\s+["\'][^"\']+["\']\s+does\s+not\s+exist)'),
    ]

    TRANSIENT_PATTERNS = [
        re.compile(r'(?i)(Connection\s+refused|connect:\s+connection\s+refused)'),
        re.compile(r'(?i)(RequestTimeout|i\/o\s+timeout|Client\.Timeout\s+exceeded)'),
        re.compile(r'(?i)(Temporary\s+failure\s+in\s+name\s+resolution)'),
        re.compile(r'(?i)(connection\s+reset\s+by\s+peer)'),
    ]

    INVALID_PARAM_PATTERNS = [
        re.compile(r'(?i)(InvalidParameterValue|InvalidParameter)'),
        re.compile(r'(?i)value\s+of\s+([a-zA-Z0-9_]+)\s+is\s+invalid'),
        re.compile(r'(?i)Unsupported\s+argument'),
    ]

    CAPACITY_PATTERNS = [
        re.compile(r'(?i)(InsufficientInstanceCapacity|insufficient\s+capacity\s+for\s+instance\s+type|InstanceTypeNotSupported)'),
    ]

    DRIFT_CONFLICT_PATTERNS = [
        re.compile(r'(?i)(Provider\s+produced\s+inconsistent\s+result\s+after\s+apply|Resource\s+drifted|objects\s+have\s+changed\s+outside\s+of\s+Terraform|Object\s+was\s+modified\s+outside\s+of\s+Terraform|Resource\s+has\s+been\s+changed\s+since\s+last\s+apply)'),
    ]

    @classmethod
    def detect(cls, log_text: str) -> Optional[DetectedError]:
        """
        Deterministically scan log text for known signatures.
        Returns a DetectedError instance or None if no error is detected.
        """
        if not log_text or not log_text.strip():
            return None

        # Check unfixable classes first (Safety rule: block auto-actions immediately)

        # 1. Auth errors -> HALT
        for pat in cls.AUTH_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="AccessDenied",
                    error_class="auth",
                    message="Cloud provider authentication or authorization failed (AccessDenied / Unauthorized).",
                    raw_excerpt=excerpt,
                    is_unfixable=True,
                    remediation_class="halted",
                    default_remediation="HALT. Never auto-fix. Notify human with diagnosis.",
                    max_attempts=0,
                    diagnosis=(
                        "Authentication / authorization failure detected. Credentials lack the required "
                        "IAM permissions to perform this operation. Engine has halted all automatic remediations. "
                        "A human operator must grant the appropriate IAM role/policy or verify credentials."
                    ),
                    metadata={"matched": m.group(0)},
                )

        # 2. Quota errors -> HALT
        for pat in cls.QUOTA_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="QuotaExceeded",
                    error_class="quota",
                    message="Service quota or resource limit exceeded for this account.",
                    raw_excerpt=excerpt,
                    is_unfixable=True,
                    remediation_class="halted",
                    default_remediation="HALT + human (cost/limit decision).",
                    max_attempts=0,
                    diagnosis=(
                        "Service quota or account limit reached. Automatic remediation blocked to prevent "
                        "unintended costs or resource over-subscription. Request a quota increase from the "
                        "cloud provider or adjust plan capacity parameters."
                    ),
                    metadata={"matched": m.group(0)},
                )

        # 3. Runtime errors -> HALT
        for pat in cls.RUNTIME_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="RuntimeOOMOrTimeout",
                    error_class="runtime",
                    message="Process killed or timed out during execution (OOM / apply timeout).",
                    raw_excerpt=excerpt,
                    is_unfixable=True,
                    remediation_class="halted",
                    default_remediation="HALT + human.",
                    max_attempts=0,
                    diagnosis=(
                        "Process execution was terminated due to out-of-memory (OOM) or an apply timeout. "
                        "Check system memory and workspace limits or partition large plans into modular steps."
                    ),
                    metadata={"matched": m.group(0)},
                )

        # 4. S3 BucketAlreadyExists
        m = cls.BUCKET_EXISTS_PATTERN.search(log_text)
        if m:
            excerpt = cls._extract_line(log_text, m.start())
            # Try to extract bucket name
            b_match = (
                re.search(r'creating (?:Amazon )?S3 (?:Simple Storage )?Bucket \(([^)]+)\)', log_text)
                or re.search(r'Bucket \(([^)]+)\)', log_text)
                or re.search(r'bucket\s*=\s*"([^"]+)"', log_text)
            )
            r_match = re.search(r'with (aws_s3_bucket\.[a-zA-Z0-9_]+)', log_text)
            bucket_name = b_match.group(1) if b_match else None
            resource_addr = r_match.group(1) if r_match else "aws_s3_bucket.main"

            return DetectedError(
                signature="BucketAlreadyExists",
                error_class="state_conflict",
                message=f"S3 Bucket '{bucket_name or 'unknown'}' already exists in target cloud environment.",
                raw_excerpt=excerpt,
                is_unfixable=False,
                remediation_class="auto",
                default_remediation="Import into state or suffix name.",
                max_attempts=1,
                diagnosis="Target S3 bucket exists in account. Auto-importing into state or suffixing name.",
                metadata={
                    "bucket_name": bucket_name,
                    "resource_address": resource_addr,
                },
            )

        # 5. InvalidSubnet.Range / CIDR overlap
        for pat in cls.CIDR_OVERLAP_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                cidr_match = re.search(r'CIDR\s+(?:address\s+)?[\'"]?([0-9./]+)[\'"]?', log_text)
                subnet_res = re.search(r'with (aws_subnet\.[a-zA-Z0-9_]+)', log_text)
                return DetectedError(
                    signature="InvalidSubnet.Range",
                    error_class="addressing",
                    message="Subnet CIDR block overlaps with an existing subnet in VPC.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="auto",
                    default_remediation="Compute next free CIDR from existing VPC state.",
                    max_attempts=2,
                    diagnosis="CIDR block collision detected. Recomputing next available non-overlapping CIDR block from VPC state.",
                    metadata={
                        "conflicting_cidr": cidr_match.group(1) if cidr_match else None,
                        "cidr": cidr_match.group(1) if cidr_match else None,
                        "resource_address": subnet_res.group(1) if subnet_res else "aws_subnet.main",
                    },
                )

        # 6. Dependency order / ResourceNotFound
        for pat in cls.DEPENDENCY_ORDER_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                res_match = re.search(r'with (aws_[a-zA-Z0-9_]+\.[a-zA-Z0-9_]+)', log_text)
                return DetectedError(
                    signature="ResourceNotFound",
                    error_class="ordering",
                    message="Resource dependency ordering violation; parent resource not ready or not found.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="auto",
                    default_remediation="Add depends_on / reorder in IR.",
                    max_attempts=1,
                    diagnosis="Dependency race condition or missing explicit dependency. Reordering resources in IR and injecting depends_on clauses.",
                    metadata={
                        "resource_address": res_match.group(1) if res_match else None,
                    },
                )

        # 7. HCL syntax / validate failure
        for pat in cls.HCL_SYNTAX_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="HCLSyntaxError",
                    error_class="generation",
                    message="Terraform HCL syntax or block validation failed pre-apply.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="auto",
                    default_remediation="Regenerate HCL from same IR (pre-apply, zero risk).",
                    max_attempts=2,
                    diagnosis="Malformed HCL syntax detected. Regenerating valid HCL from the Universal IR and re-validating syntax.",
                    metadata={"error_detail": m.group(0)},
                )

        # 8. SQL syntax failure
        for pat in cls.SQL_SYNTAX_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="SQLSyntaxError",
                    error_class="generation",
                    message="Database SQL DDL syntax failure.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="auto",
                    default_remediation="Regenerate DDL + dry-run validate (pre-execution).",
                    max_attempts=2,
                    diagnosis="SQL DDL parser syntax error. Regenerating sanitized dialect DDL and dry-running validation.",
                    metadata={"error_detail": m.group(0)},
                )

        # 9. Transient network / Connection refused
        for pat in cls.TRANSIENT_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="ConnectionRefused",
                    error_class="transient",
                    message="Network connection refused or timeout occurred communicating with provider endpoint.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="auto",
                    default_remediation="Retry with exponential backoff + jitter.",
                    max_attempts=3,
                    diagnosis="Transient network connection glitch or endpoint warmup delay. Retrying with exponential backoff and randomized jitter.",
                    metadata={"error_detail": m.group(0)},
                )

        # 10. Capacity: InsufficientInstanceCapacity
        for pat in cls.CAPACITY_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                inst_match = re.search(r'instance\s+type\s+[\'"]?([a-zA-Z0-9._]+)[\'"]?', log_text)
                return DetectedError(
                    signature="InsufficientInstanceCapacity",
                    error_class="capacity",
                    message="Target cloud provider has insufficient capacity for requested compute instance type in availability zone.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="approve",
                    default_remediation="Switch to fallback instance-class list.",
                    max_attempts=1,
                    diagnosis="Requested instance type is currently unavailable in the chosen zone. A proposal has been prepared to switch to a compatible alternative class, pending human confirmation.",
                    metadata={"requested_type": inst_match.group(1) if inst_match else None},
                )

        # 11. Drift Conflict
        for pat in cls.DRIFT_CONFLICT_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                return DetectedError(
                    signature="DriftConflict",
                    error_class="state",
                    message="Cloud resources were altered outside Terraform state causing drift conflict.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="approve",
                    default_remediation="Refresh + replan; destructive diff -> approve.",
                    max_attempts=1,
                    diagnosis="External drift conflict detected. State refresh and replan required. If plan introduces destructive changes, human confirmation will be requested.",
                    metadata={},
                )

        # 12. InvalidParameterValue (attribute)
        for pat in cls.INVALID_PARAM_PATTERNS:
            m = pat.search(log_text)
            if m:
                excerpt = cls._extract_line(log_text, m.start())
                param_match = re.search(r'parameter\s+([a-zA-Z0-9_.]+)', log_text) or re.search(r'argument\s+["\']?([a-zA-Z0-9_.]+)["\']?', log_text)
                return DetectedError(
                    signature="InvalidParameterValue",
                    error_class="generation",
                    message="Invalid parameter value provided to cloud resource attribute.",
                    raw_excerpt=excerpt,
                    is_unfixable=False,
                    remediation_class="approve",
                    default_remediation="LLM proposes attribute patch.",
                    max_attempts=2,
                    diagnosis="Resource attribute failed validation schema. AI Fix Proposer generated a verified attribute patch.",
                    metadata={"parameter": param_match.group(1) if param_match else None},
                )

        # 13. Generic error detected (e.g. "Error:" or "failed:")
        if re.search(r'(?i)(Error[:\s]|fatal[:\s]|panic[:\s]|failed\s+to\s+apply|glitch|exception)', log_text):
            m = re.search(r'(?i)(Error:\s+[^\n]+)', log_text)
            excerpt = m.group(1) if m else cls._extract_line(log_text, 0)
            return DetectedError(
                signature="UnknownError",
                error_class="unknown",
                message=f"Execution error: {excerpt[:120]}",
                raw_excerpt=excerpt,
                is_unfixable=False,
                remediation_class="approve",
                default_remediation="LLM proposes fix -> policy validation -> human approval.",
                max_attempts=2,
                diagnosis="Unknown error encountered during execution. Sanitized logs sent to LLM Fix Proposer for root cause diagnosis and proposal.",
                metadata={"raw_error": excerpt},
            )

        return None

    @staticmethod
    def _extract_line(text: str, pos: int) -> str:
        """Extract the single line containing character index pos."""
        start = text.rfind('\n', 0, pos)
        end = text.find('\n', pos)
        if start == -1:
            start = 0
        else:
            start += 1
        if end == -1:
            end = len(text)
        return text[start:end].strip()


error_detector = ErrorDetector()
DeterministicErrorDetector = ErrorDetector

