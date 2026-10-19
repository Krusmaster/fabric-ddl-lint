#!/usr/bin/env python3
"""fabric-ddl-lint — check T-SQL scripts against Microsoft Fabric Warehouse rules before deploy.

Usage:
    python fabric_ddl_lint.py path/to/script.sql [more.sql ...]
    python fabric_ddl_lint.py --rules rules.json schema/*.sql

Exit code 1 if any ERROR is found, else 0. Rules live in rules.json so they can be
updated as Fabric changes (and it does — IDENTITY went from unsupported to supported
in early 2026).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SEVERITY_ORDER = {"error": 2, "warning": 1, "info": 0}

DEFAULT_RULES = [
    {
        "id": "FW001",
        "severity": "error",
        "pattern": r"\bDEFAULT\s+(?!NULL\b)\S",
        "scope": "create_table",
        "message": "DEFAULT constraints are not supported in Fabric Warehouse. Set the value in INSERT/MERGE or ISNULL() in a view.",
    },
    {
        "id": "FW002",
        "severity": "warning",
        "pattern": r"\bIDENTITY\s*\(",
        "scope": "create_table",
        "message": "IDENTITY became supported in early 2026; verify on your capacity before relying on it. Older guidance says generate keys in Spark.",
    },
    {
        "id": "FW003",
        "severity": "warning",
        "pattern": r"\bDATETIME2\b(?!\s*\()",
        "scope": "any",
        "message": "DATETIME2 without explicit precision defaults to 7, which Delta cannot store. Use DATETIME2(6) or lower.",
    },
    {
        "id": "FW004",
        "severity": "error",
        "pattern": r"\b(PRIMARY\s+KEY|UNIQUE|FOREIGN\s+KEY)\b(?![^;]*\bNOT\s+ENFORCED\b)",
        "scope": "any",
        "message": "PRIMARY KEY / UNIQUE / FOREIGN KEY must be declared NOT ENFORCED (and PK/UNIQUE NONCLUSTERED).",
    },
    {
        "id": "FW005",
        "severity": "error",
        "pattern": r"\bALTER\s+TABLE\b[^;]*\b(ALTER|DROP)\s+COLUMN\b",
        "scope": "any",
        "message": "ALTER TABLE ... ALTER/DROP COLUMN is not supported. Recreate the table or add a nullable column only.",
    },
    {
        "id": "FW006",
        "severity": "error",
        "pattern": r"\bCREATE\s+(UNIQUE\s+|CLUSTERED\s+|NONCLUSTERED\s+)*INDEX\b",
        "scope": "any",
        "message": "CREATE INDEX is not supported in Fabric Warehouse.",
    },
    {
        "id": "FW007",
        "severity": "info",
        "pattern": r"\bVARCHAR\s*\(\s*MAX\s*\)",
        "scope": "any",
        "message": "VARCHAR(MAX) works but costs in Delta storage. Prefer VARCHAR(8000) when it fits.",
    },
    {
        "id": "FW008",
        "severity": "warning",
        "pattern": r"\bWHEN\s+MATCHED\b[^;]*\bTHEN\s+DELETE\b",
        "scope": "any",
        "message": "MERGE with DELETE clause is not reliably supported. Use UPDATE/INSERT only and handle deletes separately.",
    },
    {
        "id": "FW009",
        "severity": "error",
        "pattern": None,
        "scope": "batch_order",
        "message": "CREATE VIEW must be the first statement in a batch. Put GO before it.",
    },
]


@dataclass
class Finding:
    file: str
    line: int
    rule_id: str
    severity: str
    message: str

    def __str__(self) -> str:
        return f"{self.file}:{self.line}: {self.severity.upper()} {self.rule_id} {self.message}"


def strip_comments(sql: str) -> str:
    """Blank out comments but keep line count so line numbers stay correct."""
    sql = re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), sql, flags=re.S)
    sql = re.sub(r"--[^\n]*", "", sql)
    return sql


def split_batches(sql: str) -> list[tuple[int, str]]:
    """Split on GO lines. Returns (start_line, text) per batch."""
    batches, start, buf = [], 1, []
    for i, line in enumerate(sql.splitlines(), start=1):
        if re.fullmatch(r"\s*GO\s*(\d+)?\s*", line, flags=re.I):
            batches.append((start, "\n".join(buf)))
            start, buf = i + 1, []
        else:
            buf.append(line)
    batches.append((start, "\n".join(buf)))
    return batches


def statements(batch: str) -> list[str]:
    return [s for s in re.split(r";", batch) if s.strip()]


def lint_text(sql: str, filename: str, rules: list[dict]) -> list[Finding]:
    clean = strip_comments(sql)
    findings: list[Finding] = []

    for start_line, batch in split_batches(clean):
        # FW009: CREATE VIEW must open its batch
        for rule in rules:
            if rule["scope"] == "batch_order":
                stmts = statements(batch)
                for idx, stmt in enumerate(stmts):
                    if re.search(r"\bCREATE\s+(OR\s+ALTER\s+)?VIEW\b", stmt, re.I) and idx > 0:
                        line = start_line + batch[: batch.find(stmt)].count("\n")
                        findings.append(Finding(filename, line, rule["id"], rule["severity"], rule["message"]))

        for rule in rules:
            if not rule.get("pattern"):
                continue
            rx = re.compile(rule["pattern"], re.I | re.S)
            targets = statements(batch)
            if rule["scope"] == "create_table":
                targets = [s for s in targets if re.search(r"\bCREATE\s+TABLE\b", s, re.I)]
            for stmt in targets:
                for m in rx.finditer(stmt):
                    offset = batch.find(stmt) + m.start()
                    line = start_line + batch[:offset].count("\n")
                    findings.append(Finding(filename, line, rule["id"], rule["severity"], rule["message"]))

    findings.sort(key=lambda f: (f.line, f.rule_id))
    return findings


def load_rules(path: str | None) -> list[dict]:
    if not path:
        return DEFAULT_RULES
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Lint T-SQL for Microsoft Fabric Warehouse compatibility.")
    ap.add_argument("files", nargs="+", help=".sql files to check")
    ap.add_argument("--rules", help="JSON rules file (defaults to built-in rules)")
    ap.add_argument("--min-severity", default="info", choices=SEVERITY_ORDER, help="hide findings below this level")
    ap.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = ap.parse_args(argv)

    rules = load_rules(args.rules)
    all_findings: list[Finding] = []
    for f in args.files:
        text = Path(f).read_text(encoding="utf-8")
        all_findings += lint_text(text, f, rules)

    shown = [x for x in all_findings if SEVERITY_ORDER[x.severity] >= SEVERITY_ORDER[args.min_severity]]
    if args.json:
        print(json.dumps([x.__dict__ for x in shown], indent=2))
    else:
        for x in shown:
            print(x)
        errors = sum(1 for x in all_findings if x.severity == "error")
        warnings = sum(1 for x in all_findings if x.severity == "warning")
        print(f"\n{len(shown)} finding(s): {errors} error(s), {warnings} warning(s)")
    return 1 if any(x.severity == "error" for x in all_findings) else 0


if __name__ == "__main__":
    sys.exit(main())
