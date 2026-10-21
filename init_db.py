"""
Loads sql/01_schema.sql and sql/02_seed.sql into MySQL.

    python init_db.py              -> builds green_campus_db (wipes it first!)
    python init_db.py my_test_db   -> same thing under another name (the tests use this)

You can also just run the two .sql files in MySQL Workbench, this is only a shortcut.
"""
import sys
from pathlib import Path

import mysql.connector

import config

SQL_DIR = Path(__file__).parent / "sql"


def split_statements(script):
    # mysql-connector can't handle DELIMITER (it's a client command, not SQL),
    # so we split the file ourselves.
    statements, buf, delim = [], [], ";"
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("DELIMITER"):
            delim = stripped.split()[1]
            continue
        if not buf and (stripped == "" or stripped.startswith("--")):
            continue
        buf.append(line)
        if stripped.endswith(delim):
            stmt = "\n".join(buf).rstrip()
            stmt = stmt[: -len(delim)]
            statements.append(stmt)
            buf = []
    return statements


def load(db_name=None):
    db_name = db_name or config.DB_NAME
    conn = mysql.connector.connect(
        host=config.DB_HOST, port=config.DB_PORT,
        user=config.DB_USER, password=config.DB_PASSWORD,
    )
    cur = conn.cursor()
    for fname in ("01_schema.sql", "02_seed.sql"):
        script = (SQL_DIR / fname).read_text(encoding="utf-8")
        script = script.replace("green_campus_db", db_name)
        for stmt in split_statements(script):
            cur.execute(stmt)
    conn.commit()
    cur.close()
    conn.close()


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else None
    load(name)
    print("Database ready:", name or config.DB_NAME)
