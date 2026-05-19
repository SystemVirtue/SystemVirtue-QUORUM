import re

PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"eyJ[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+?\.[A-Za-z0-9_\-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.=]+", re.I),
    re.compile(r"(?im)^([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*).+$"),
    re.compile(r"(postgres(?:ql)?://[^:\s]+:)[^@\s]+(@)", re.I),
    re.compile(r"rk_live_[A-Za-z0-9]{12,}"),
]


def redact(text: str) -> str:
    redacted = text
    for pattern in PATTERNS:
        if pattern.pattern.startswith("(postgres"):
            redacted = pattern.sub(r"\1[REDACTED]\2", redacted)
        elif "(?im)^" in pattern.pattern:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted
