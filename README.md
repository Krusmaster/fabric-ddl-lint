# fabric-ddl-lint

**The problem.** Fabric Warehouse speaks T-SQL, but it is not SQL Server. Scripts copied from
Azure SQL or Synapse look right, pass code review, and fail at deploy — or worse, deploy and
misbehave. A `DEFAULT` constraint, a `DATETIME2` without precision, a `PRIMARY KEY` without
`NOT ENFORCED`, a `CREATE VIEW` that is not first in its batch. Each one costs a deploy cycle,
and the knowledge of what breaks usually lives in one engineer's head.

**What this does.** Reads your `.sql` files and tells you, line by line, what Fabric Warehouse
will refuse. Exit code 1 on errors, so it can block a pipeline. No dependencies.

```
python fabric_ddl_lint.py schema/*.sql
python fabric_ddl_lint.py --min-severity warning --json schema/*.sql
```

```
examples/bad.sql:6: ERROR FW001 DEFAULT constraints are not supported in Fabric Warehouse. ...
examples/bad.sql:8: ERROR FW004 PRIMARY KEY / UNIQUE / FOREIGN KEY must be declared NOT ENFORCED ...
examples/bad.sql:9: ERROR FW009 CREATE VIEW must be the first statement in a batch. Put GO before it.
```

## Rules

| ID | Severity | Catches |
| --- | --- | --- |
| FW001 | error | `DEFAULT` constraints in `CREATE TABLE` |
| FW002 | warning | `IDENTITY(...)` — supported since early 2026; verify on your capacity |
| FW003 | warning | `DATETIME2` without explicit precision (defaults to 7, which Delta cannot store) |
| FW004 | error | `PRIMARY KEY` / `UNIQUE` / `FOREIGN KEY` without `NOT ENFORCED` |
| FW005 | error | `ALTER TABLE ... ALTER/DROP COLUMN` |
| FW006 | error | `CREATE INDEX` |
| FW007 | info | `VARCHAR(MAX)` — works, costs in Delta storage |
| FW008 | warning | `MERGE ... WHEN MATCHED THEN DELETE` |
| FW009 | error | `CREATE VIEW` not first in its batch (missing `GO`) |

Rules are plain regex + severity in a list. Override with `--rules my_rules.json` when Fabric
changes — and it will.

## In CI

```yaml
- run: python fabric_ddl_lint.py --min-severity error warehouse/**/*.sql
```

## Limits

v0.1 is regex-based, not a SQL parser. It catches the common cases and will false-positive on
exotic syntax. Open an issue with the statement and I will add a test.

## Works on

| Platform | Status |
| --- | --- |
| Fabric Warehouse | yes — that is its purpose |
| Databricks / Snowflake | not applicable (different SQL dialects) |
| Local Python | yes — lints files, no dependencies |

## License

MIT
