import re
from typing import List, Union

# Regex patterns for sensitive data
PATTERNS = [
    # AWS Access Key IDs
    (re.compile(r'\b(A3T[A-Z0-9]|AKIA|AGPA|AIDA|AROA|AIPA|ANPA|ANVA|ASIA)[A-Z0-9]{16}\b'), '[REDACTED_AWS_KEY_ID]'),
    
    # Generic Secret keys, Passwords, Tokens with assignment
    (re.compile(r'(?i)(aws_secret_access_key|secret[_-]?key|password|passwd|token|bearer|api[_-]?key|auth[_-]?token|client[_-]?secret)\s*[:=]\s*["\']?([a-zA-Z0-9/_+=.-]{8,})["\']?'), r'\1="[REDACTED_SECRET]"'),

    # Database connection strings (Postgres, MySQL, Mongo, Redis, etc.)
    (re.compile(r'(?i)(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql):\/\/(?:[^:@\s\n]+):(?:[^@\s\n]+)@([^\s\n\'"]+)'), r'\1://[REDACTED_USER]:[REDACTED_PASSWORD]@\2'),
    (re.compile(r'(?i)(postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|mssql):\/\/[^\s\n\'"]+:[^\s\n\'"]+@'), r'\1://[REDACTED_CREDS]@'),

    # JWT Tokens (3 base64url segments separated by dots)
    (re.compile(r'\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9_-]+\b'), '[REDACTED_JWT]'),

    # Authorization Bearer headers
    (re.compile(r'(?i)bearer\s+[a-zA-Z0-9._~+/-]+=*'), 'Bearer [REDACTED_TOKEN]'),

    # Private key blocks
    (re.compile(r'-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]*?-----END [A-Z ]+PRIVATE KEY-----'), '[REDACTED_PRIVATE_KEY]'),
]


def sanitize_text(text: str) -> str:
    """Sanitize secrets, tokens, connection strings, and keys from text."""
    if not text:
        return ""
    sanitized = text
    for pattern, replacement in PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)
    return sanitized


def sanitize_logs(logs: Union[List[str], str], max_lines: int = 50) -> str:
    """
    Sanitize log lines and cap to the last `max_lines` (default 50).
    Ensures credential isolation before log excerpt is sent to LLM.
    """
    if isinstance(logs, str):
        lines = logs.splitlines()
    else:
        lines = list(logs)

    # Slice the last max_lines
    tail = lines[-max_lines:] if len(lines) > max_lines else lines
    raw_tail = "\n".join(tail)
    return sanitize_text(raw_tail)


# Alias
sanitize_for_prompt = sanitize_logs

