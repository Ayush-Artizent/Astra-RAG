"""Row-aware CSV chunking: one chunk per row (columns named in every chunk), plus one summary chunk per file."""
import csv
import io

from ...config import CHUNK_MAX_TOKENS, CSV_MAX_ROWS
from .md_chunker import RawChunk
from .tokens import count_tokens


def chunk_csv(text: str, filename: str) -> tuple[list[RawChunk], list[str]]:
    """Return (chunks, warnings)."""
    rows = _read_rows(text)
    if not rows:
        return [], []
    columns = [c.strip() or f"column_{i + 1}" for i, c in enumerate(rows[0])]
    data = rows[1:]
    warnings: list[str] = []
    if len(data) > CSV_MAX_ROWS:
        warnings.append(f"only the first {CSV_MAX_ROWS} of {len(data)} rows were indexed")
        data = data[:CSV_MAX_ROWS]

    key_col = _key_column(columns)
    chunks = [_summary(filename, columns, len(data))]
    for number, row in enumerate(data, start=1):
        key = row[key_col].strip() if key_col < len(row) else ""
        chunks.append(RawChunk(_render_row(number, columns, row), None, None, (), "csv_row",
                               {"row_start": number, "row_end": number, "row_key": key, "columns": columns}))
    return chunks, warnings


def _key_column(columns: list[str]) -> int:
    """The id-like column (id / key / ...) if there is one, else the first."""
    for i, col in enumerate(columns):
        if col.lower() in ("id", "key", "ref", "no", "number") or col.lower().endswith(("_id", " id")):
            return i
    return 0


def _read_rows(text: str) -> list[list[str]]:
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]


def _render_row(number: int, columns: list[str], row: list[str]) -> str:
    lines = [f"Row {number}"]
    lines += [f"{col}: {val.strip()}" for col, val in zip(columns, row) if val.strip()]
    lines += [f"extra_{i + 1}: {val.strip()}" for i, val in enumerate(row[len(columns):]) if val.strip()]
    text = "\n".join(lines)
    while count_tokens(text) > CHUNK_MAX_TOKENS - 10:  # a pathological row must still fit the encoder
        text = text[: int(len(text) * 0.8)].rstrip() + " …"
    return text


def _summary(filename: str, columns: list[str], row_count: int) -> RawChunk:
    text = f"CSV file {filename}\nColumns: {', '.join(columns)}\nRows: {row_count}"
    return RawChunk(text, None, None, (), "csv_summary", {"columns": columns, "row_count": row_count})
