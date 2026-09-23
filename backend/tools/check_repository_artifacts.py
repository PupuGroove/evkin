"""Fail when tracked files match EVKIN runtime/data artifact patterns."""
from __future__ import annotations

import re
import subprocess

FORBIDDEN = (
    re.compile(r"(^|/)(backend/data|outputs?|exports?|temp|tmp)(/|$)", re.IGNORECASE),
    re.compile(r"\.(duckdb|db|sqlite|sqlite3)(\.|$)|\.log$", re.IGNORECASE),
    re.compile(r"(^|/)\.env($|\.)", re.IGNORECASE),
    re.compile(r"(^|/)~\$[^/]*\.(xlsx|xls|docx|pptx)$", re.IGNORECASE),
)
ALLOWED_ENV_TEMPLATES = frozenset({".env.example", ".env.sample"})


def main() -> None:
    result = subprocess.run(
        ["git", "ls-files", "-z"], check=True, capture_output=True
    )
    tracked = [item.decode("utf-8") for item in result.stdout.split(b"\0") if item]
    violations = sorted(
        path for path in tracked
        if path.rsplit("/", 1)[-1].lower() not in ALLOWED_ENV_TEMPLATES
        and any(rule.search(path) for rule in FORBIDDEN)
    )
    if violations:
        raise SystemExit("Forbidden tracked runtime/data artifacts:\n" + "\n".join(violations))
    print(f"Repository artifact check passed ({len(tracked)} tracked files inspected)")


if __name__ == "__main__":
    main()
