"""Row-aware CSV chunking: header repeated in every chunk, plus one summary chunk per file."""
import csv
import io

from ...config import CHUNK_MAX_TOKENS, CHUNK_TARGET_TOKENS, CSV_MAX_ROWS, CSV_SUMMARY_SAMPLE_ROWS
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

    header = "Columns: " + ", ".join(columns)
    header_tokens = count_tokens(header)
    chunks = [_summary(filename, columns, data, header)]
    group: list[str] = []
    first = 1
    tokens = header_tokens
    for number, row in enumerate(data, start=1):
        rendered = _render_row(number, columns, row, header_tokens)
        t = count_tokens(rendered)
        if group and tokens + t > CHUNK_TARGET_TOKENS:
            chunks.append(_rows_chunk(header, group, first, number - 1, columns))
            group, first, tokens = [], number, header_tokens
        group.append(rendered)
        tokens += t
    if group:
        chunks.append(_rows_chunk(header, group, first, first + len(group) - 1, columns))
    return chunks, warnings


def _read_rows(text: str) -> list[list[str]]:
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    return [r for r in csv.reader(io.StringIO(text), dialect) if any(c.strip() for c in r)]


def _render_row(number: int, columns: list[str], row: list[str], header_tokens: int) -> str:
    lines = [f"Row {number}"]
    lines += [f"{col}: {val.strip()}" for col, val in zip(columns, row) if val.strip()]
    lines += [f"extra_{i + 1}: {val.strip()}" for i, val in enumerate(row[len(columns):]) if val.strip()]
    text = "\n".join(lines)
    budget = CHUNK_MAX_TOKENS - header_tokens - 10
    while count_tokens(text) > budget:  # a pathological row must still fit the encoder
        text = text[: int(len(text) * 0.8)].rstrip() + " …"
    return text


def _rows_chunk(header: str, group: list[str], first: int, last: int, columns: list[str]) -> RawChunk:
    return RawChunk(header + "\n\n" + "\n\n".join(group), None, None, (), "csv_rows",
                    {"row_start": first, "row_end": last, "columns": columns})


def _summary(filename: str, columns: list[str], data: list[list[str]], header: str) -> RawChunk:
    header_tokens = count_tokens(header)
    lines = [f"CSV file {filename}", header, f"Rows: {len(data)}"]
    for number, row in enumerate(data[:CSV_SUMMARY_SAMPLE_ROWS], start=1):
        lines.append(_render_row(number, columns, row, header_tokens))
    return RawChunk("\n".join(lines), None, None, (), "csv_summary", {"columns": columns})
