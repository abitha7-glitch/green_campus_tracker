"""Small helpers around mysql-connector so the routes stay readable."""
import warnings

import mysql.connector
from mysql.connector import errorcode, pooling

import config

_pool = None


def get_pool():
    global _pool
    if _pool is None:
        _pool = pooling.MySQLConnectionPool(
            pool_name="greencampus",
            pool_size=5,
            host=config.DB_HOST, port=config.DB_PORT,
            user=config.DB_USER, password=config.DB_PASSWORD,
            database=config.DB_NAME,
            autocommit=True,  # every write here is a single statement anyway
        )
    return _pool


def reset_pool():
    # used by the tests when they point the app at a different database
    global _pool
    _pool = None


def query(sql, params=None, one=False):
    conn = get_pool().get_connection()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cur.close()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def query_with_columns(sql, params=None):
    """Same as query() but also returns the column names (for the Queries page)."""
    conn = get_pool().get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.close()
        return cols, rows
    finally:
        conn.close()


def scalar(sql, params=None):
    conn = get_pool().get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        row = cur.fetchone()
        cur.close()
        return row[0] if row else None
    finally:
        conn.close()


def execute(sql, params=None):
    """INSERT / UPDATE / DELETE. Returns rowcount. Rolls back and re-raises on error."""
    conn = get_pool().get_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        n = cur.rowcount
        conn.commit()
        cur.close()
        return n
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def call_proc(name, args):
    conn = get_pool().get_connection()
    try:
        cur = conn.cursor()
        cur.callproc(name, args)
        cols, rows = [], []
        # newer mysql-connector versions warn that stored_results() will become a
        # property, but it's the only way that works on both old and new versions
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            results = list(cur.stored_results())
        for result in results:
            cols = [d[0] for d in result.description]
            rows = result.fetchall()
        cur.close()
        return cols, rows
    finally:
        conn.close()


def read_only_select(sql):
    """For the SQL console. Runs inside a READ ONLY transaction so even if something
    slips past the keyword check, the server refuses to write."""
    conn = get_pool().get_connection()
    try:
        cur = conn.cursor()
        cur.execute("START TRANSACTION READ ONLY")
        cur.execute(sql)
        rows = cur.fetchmany(500)
        cols = [d[0] for d in cur.description] if cur.description else []
        cur.fetchall()  # drain anything past 500
        conn.rollback()
        cur.close()
        return cols, rows
    finally:
        conn.close()


# MySQL 8 uses 3819 for a failed CHECK, MariaDB (XAMPP) uses 4025
CHECK_FAILED = (3819, 4025)


def friendly_error(err):
    """Turn a mysql error into something a person can read."""
    if not isinstance(err, mysql.connector.Error):
        return str(err)
    code = err.errno
    msg = err.msg or ""
    if code == errorcode.ER_DUP_ENTRY:
        val = msg.split("'")[1] if "'" in msg else "that value"
        return f"'{val}' is already in use. It has to be unique."
    if code == errorcode.ER_ROW_IS_REFERENCED_2 or code == errorcode.ER_ROW_IS_REFERENCED:
        return "Can't delete this, other records still point to it (foreign key RESTRICT)."
    if code == errorcode.ER_NO_REFERENCED_ROW_2 or code == errorcode.ER_NO_REFERENCED_ROW:
        return "The record you linked to doesn't exist."
    if code in CHECK_FAILED:
        return "The database rejected a value that breaks a CHECK rule (negative or zero where it isn't allowed)."
    if code == errorcode.WARN_DATA_TRUNCATED:
        return "That value isn't one of the allowed options."
    if code == errorcode.ER_BAD_NULL_ERROR:
        return "A required field was left empty."
    return f"Database error {code}: {msg}"
