from fabric_ddl_lint import DEFAULT_RULES, lint_text


def ids(sql: str) -> list[str]:
    return [f.rule_id for f in lint_text(sql, "t.sql", DEFAULT_RULES)]


def test_clean_script_passes():
    sql = """
    CREATE TABLE dbo.orders (
        order_id   VARCHAR(10) NOT NULL,
        created_at DATETIME2(6) NOT NULL,
        amount     DECIMAL(18,2) NULL
    );
    GO
    ALTER TABLE dbo.orders ADD CONSTRAINT pk_orders PRIMARY KEY NONCLUSTERED (order_id) NOT ENFORCED;
    GO
    CREATE VIEW dbo.v_orders AS SELECT order_id, ISNULL(amount, 0) AS amount FROM dbo.orders;
    """
    assert ids(sql) == []


def test_default_constraint_flagged():
    sql = "CREATE TABLE t (a INT DEFAULT 0);"
    assert "FW001" in ids(sql)


def test_default_null_not_flagged():
    sql = "CREATE TABLE t (a INT DEFAULT NULL);"
    assert "FW001" not in ids(sql)


def test_identity_is_warning():
    f = lint_text("CREATE TABLE t (id INT IDENTITY(1,1));", "t.sql", DEFAULT_RULES)
    assert any(x.rule_id == "FW002" and x.severity == "warning" for x in f)


def test_datetime2_without_precision():
    assert "FW003" in ids("CREATE TABLE t (ts DATETIME2);")
    assert "FW003" not in ids("CREATE TABLE t (ts DATETIME2(6));")


def test_pk_without_not_enforced():
    assert "FW004" in ids("ALTER TABLE t ADD CONSTRAINT pk PRIMARY KEY (id);")
    assert "FW004" not in ids("ALTER TABLE t ADD CONSTRAINT pk PRIMARY KEY NONCLUSTERED (id) NOT ENFORCED;")


def test_alter_drop_column():
    assert "FW005" in ids("ALTER TABLE t DROP COLUMN a;")
    assert "FW005" not in ids("ALTER TABLE t ADD b INT NULL;")


def test_create_index():
    assert "FW006" in ids("CREATE NONCLUSTERED INDEX ix ON t (a);")


def test_view_not_first_in_batch():
    sql = "SELECT 1;\nCREATE VIEW v AS SELECT 1 AS x;"
    assert "FW009" in ids(sql)


def test_view_first_after_go_ok():
    sql = "SELECT 1;\nGO\nCREATE VIEW v AS SELECT 1 AS x;"
    assert "FW009" not in ids(sql)


def test_comments_ignored_but_lines_kept():
    sql = "-- DEFAULT 0 in a comment\n/* IDENTITY(1,1) */\nCREATE TABLE t (a INT DEFAULT 1);"
    f = lint_text(sql, "t.sql", DEFAULT_RULES)
    assert [x.rule_id for x in f] == ["FW001"]
    assert f[0].line == 3


def test_merge_delete_warning():
    sql = "MERGE t USING s ON t.id = s.id WHEN MATCHED THEN DELETE;"
    assert "FW008" in ids(sql)
