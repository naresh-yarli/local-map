"""Read-only PostgreSQL MCP server.

The chat client starts this process and speaks JSON-RPC over stdin/stdout.
Do not print to stdout. Tool results are return values.
"""

import os
import re
from pathlib import Path
from urllib.parse import urlparse

import psycopg
from dotenv import load_dotenv
from mcp.server import MCPServer
from psycopg.rows import dict_row

# The client config does not receive this file. The password stays here.
load_dotenv(Path(__file__).resolve().parent / ".env")

mcp = MCPServer("PostgresReader")

MAX_ROWS = 200
STATEMENT_TIMEOUT_MS = 15000
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_READ_STATEMENT = re.compile(r"^(select|with)\b", re.IGNORECASE)


def _database_uri() -> str:
    uri = os.environ.get("DATABASE_URI", "").strip()
    if not uri:
        raise RuntimeError("DATABASE_URI is not set")
    return uri


def _redact(message: str) -> str:
    """Drop the connection URI and password if a driver error repeats them."""
    uri = os.environ.get("DATABASE_URI", "").strip()
    if uri:
        message = message.replace(uri, "postgresql://[redacted]")
        password = urlparse(uri).password
        if password:
            message = message.replace(password, "[redacted]")
    return message


def _format_rows(rows: list[dict], truncated: bool) -> str:
    if not rows:
        return "(no rows)"
    columns = list(rows[0].keys())
    lines = [" | ".join(columns)]
    for row in rows:
        lines.append(" | ".join("" if row[column] is None else str(row[column]) for column in columns))
    if truncated:
        lines.append(f"... truncated to {MAX_ROWS} rows")
    return "\n".join(lines)


def _single_read_statement(sql: str) -> str | None:
    """Reject anything other than one SELECT or WITH statement.

    A read-only transaction is the real guard. This check gives the model
    a clear error before PostgreSQL sees a write.
    """
    stripped = sql.strip()
    if not stripped:
        return "Error: sql is required."

    body = stripped[:-1].rstrip() if stripped.endswith(";") else stripped
    if ";" in body:
        return "Error: send one statement. Multiple statements are refused."
    if _READ_STATEMENT.match(body.lstrip()):
        return None
    return "Error: only a single SELECT statement is allowed."


def _read_only(sql: str, params: tuple = ()) -> str:
    try:
        with psycopg.connect(
            _database_uri(),
            row_factory=dict_row,
            options=f"-c statement_timeout={STATEMENT_TIMEOUT_MS}",
        ) as conn:
            conn.read_only = True
            with conn.transaction():
                cursor = conn.execute(sql, params)
                if cursor.description is None:
                    return "Error: query returned no result."
                fetched = cursor.fetchmany(MAX_ROWS + 1)
    except Exception as exc:
        message = _redact(str(exc).splitlines()[0])
        return f"Error: {message}"

    truncated = len(fetched) > MAX_ROWS
    return _format_rows(fetched[:MAX_ROWS], truncated)


@mcp.tool()
def list_tables() -> str:
    """List tables and views in the public schema."""
    return _read_only(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name
        """
    )


@mcp.tool()
def describe_table(table_name: str) -> str:
    """List columns for one table or view in the public schema.

    Args:
        table_name: Unqualified name, such as orders or customers.
    """
    if not _IDENTIFIER.fullmatch(table_name or ""):
        return "Error: table_name must be a plain name, such as orders."

    result = _read_only(
        """
        SELECT column_name, data_type, is_nullable
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        ORDER BY ordinal_position
        """,
        (table_name,),
    )
    if result == "(no rows)":
        return f"Error: public.{table_name} was not found."
    return result


@mcp.tool()
def run_query(sql: str) -> str:
    """Run one read-only SELECT. Results are capped so a large table cannot flood the context window.

    Args:
        sql: A single SELECT statement. WITH queries are allowed. Writes are refused.
    """
    rejected = _single_read_statement(sql)
    if rejected:
        return rejected
    return _read_only(sql)


if __name__ == "__main__":
    mcp.run(transport="stdio")
