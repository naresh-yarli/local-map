"""Local File Inspector — a read-only MCP server for safe file previews.

The chat client starts this process and speaks JSON-RPC over stdin/stdout.
Do not print to stdout. Tool results must be return values.
"""

import os
from datetime import datetime
from pathlib import Path

from mcp.server import MCPServer

mcp = MCPServer("LocalFileInspector")

MAX_PREVIEW_LINES = 200
MAX_LIST_ENTRIES = 200
MAX_SEARCH_RESULTS = 100
MAX_FILES_VISITED = 5000
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def _allowed_roots() -> list[Path]:
    """Directories the model is allowed to read.

    INSPECTOR_ROOTS is a path-separator list (colon on macOS and Linux).
    When it is unset, the sandbox is the user's home directory.
    """
    raw = os.environ.get("INSPECTOR_ROOTS", "").strip()
    if not raw:
        return [Path.home().resolve()]

    roots = [
        Path(part).expanduser().resolve()
        for part in raw.split(os.pathsep)
        if part.strip()
    ]
    return roots or [Path.home().resolve()]


def _is_allowed(path: Path) -> bool:
    return any(path == root or path.is_relative_to(root) for root in _allowed_roots())


def _resolve_allowed(raw_path: str) -> Path:
    """Resolve ~, symlinks, and '..', then reject paths outside the sandbox."""
    if not raw_path or not str(raw_path).strip():
        raise ValueError("path is required")

    target = Path(raw_path).expanduser().resolve()
    if _is_allowed(target):
        return target

    roots = ", ".join(str(root) for root in _allowed_roots())
    raise PermissionError(f"{target} is outside the allowed roots ({roots})")


def _format_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} B"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{num_bytes} B"


def _iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in filenames:
            yield Path(dirpath) / filename


@mcp.tool()
def list_directory(path: str) -> str:
    """List files and folders with type, size, and last-modified time.

    Args:
        path: Directory to list. Use an absolute path or a path starting with ~.
    """
    try:
        target = _resolve_allowed(path)
    except (PermissionError, ValueError) as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Error: {target} does not exist."
    if not target.is_dir():
        return f"Error: {target} is not a directory."

    try:
        entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
    except OSError as exc:
        return f"Error: cannot read {target}: {exc}"

    rows: list[str] = []
    for item in entries[:MAX_LIST_ENTRIES]:
        try:
            stat = item.stat()
            kind = "dir" if item.is_dir() else "file"
            size = "-" if item.is_dir() else _format_size(stat.st_size)
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            rows.append(f"{kind:4}  {size:>10}  {modified}  {item.name}")
        except OSError as exc:
            rows.append(f"err   {'-':>10}  {'-':16}  {item.name}  ({exc})")

    body = "\n".join(rows) if rows else "(empty)"
    suffix = ""
    if len(entries) > MAX_LIST_ENTRIES:
        suffix = f"\n... truncated to {MAX_LIST_ENTRIES} entries"
    return f"{target}  ({len(entries)} entries)\n{body}{suffix}"


@mcp.tool()
def read_file_head(path: str, lines: int = 50) -> str:
    """Read the first lines of a text file so a large file cannot flood the context window.

    Args:
        path: Text or log file to preview.
        lines: How many lines to return. Defaults to 50 and is capped at 200.
    """
    try:
        target = _resolve_allowed(path)
    except (PermissionError, ValueError) as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Error: {target} does not exist."
    if not target.is_file():
        return f"Error: {target} is not a file."

    try:
        with target.open("rb") as handle:
            if b"\x00" in handle.read(8192):
                return f"Error: {target} looks like a binary file. Preview is for text and logs."
    except OSError as exc:
        return f"Error: cannot read {target}: {exc}"

    requested = max(1, min(int(lines), MAX_PREVIEW_LINES))
    try:
        with target.open("r", encoding="utf-8", errors="ignore") as handle:
            preview = "".join(handle.readline() for _ in range(requested))
    except OSError as exc:
        return f"Error: cannot read {target}: {exc}"

    if not preview:
        return f"{target}\n(file is empty)"

    numbered = [f"{index:4} | {line}" for index, line in enumerate(preview.splitlines(), start=1)]
    if len(numbered) >= requested:
        numbered.append(f"... preview capped at {requested} lines")
    return f"{target}\n" + "\n".join(numbered)


@mcp.tool()
def search_files_by_extension(path: str, ext: str) -> str:
    """Find files under a directory that end with an extension such as .py, .csv, or .log.

    Args:
        path: Directory to search. The walk skips .git, .venv, and __pycache__.
        ext: Extension to match. A leading dot is optional.
    """
    try:
        target = _resolve_allowed(path)
    except (PermissionError, ValueError) as exc:
        return f"Error: {exc}"

    if not target.exists():
        return f"Error: {target} does not exist."
    if not target.is_dir():
        return f"Error: {target} is not a directory."

    cleaned = ext.strip().lower()
    if not cleaned:
        return "Error: extension is required, for example .py or .log."
    if not cleaned.startswith("."):
        cleaned = f".{cleaned}"
    if len(cleaned) > 10 or any(char in cleaned for char in "*?[]/\\"):
        return "Error: extension must look like .py, .csv, or .log."

    matches: list[Path] = []
    visited = 0
    truncated = False
    try:
        for candidate in _iter_files(target):
            visited += 1
            if visited > MAX_FILES_VISITED:
                truncated = True
                break
            if candidate.suffix.lower() != cleaned:
                continue
            resolved = candidate.resolve()
            if not _is_allowed(resolved):
                continue
            matches.append(resolved)
            if len(matches) >= MAX_SEARCH_RESULTS:
                truncated = True
                break
    except OSError as exc:
        return f"Error: cannot search {target}: {exc}"

    lines = [f"{target}  ({cleaned}, {len(matches)} files)"]
    for match in sorted(matches, key=lambda item: str(item).lower()):
        try:
            display = match.relative_to(target)
        except ValueError:
            display = match
        lines.append(f"  {display}")
    if len(matches) == 0:
        lines.append("(no matches)")
    if truncated:
        lines.append(
            f"... stopped after {visited} files visited or {MAX_SEARCH_RESULTS} matches"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
