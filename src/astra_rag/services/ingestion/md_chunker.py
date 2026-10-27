"""Heading-aware markdown chunking. Code fences and tables are kept whole where they fit."""
import re
from dataclasses import dataclass, field

from ...config import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS
from .tokens import count_tokens

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class RawChunk:
    text: str
    start: int | None      # 1-based line range in the source text
    end: int | None
    heading_path: tuple[str, ...]
    kind: str              # text | table | code | csv_rows | csv_summary
    extra: dict = field(default_factory=dict)


@dataclass
class _Block:
    text: str
    kind: str              # heading | text | table | code
    start: int
    end: int
    path: tuple[str, ...]


def chunk_markdown(text: str) -> list[RawChunk]:
    blocks: list[_Block] = []
    for block in _parse_blocks(text):
        if count_tokens(block.text) > CHUNK_MAX_TOKENS:
            blocks.extend(_split_block(block))
        else:
            blocks.append(block)
    return _pack(blocks)


def document_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1:
            return m.group(2).strip() or fallback
        if line.strip():
            break
    return fallback


def _parse_blocks(text: str) -> list[_Block]:
    lines = text.splitlines()
    n, i = len(lines), 0
    stack: list[tuple[int, str]] = []
    blocks: list[_Block] = []

    def path() -> tuple[str, ...]:
        return tuple(title for _, title in stack)

    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _FENCE.match(line):
            marker, j = line.strip()[:3], i + 1
            while j < n and not lines[j].strip().startswith(marker):
                j += 1
            end = min(j, n - 1)
            blocks.append(_Block("\n".join(lines[i:end + 1]), "code", i + 1, end + 1, path()))
            i = end + 1
            continue
        m = _HEADING.match(line)
        if m:
            level = len(m.group(1))
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, m.group(2).strip()))
            blocks.append(_Block(line.strip(), "heading", i + 1, i + 1, path()))
            i += 1
            continue
        is_table = line.lstrip().startswith("|")
        j = i
        while (j < n and lines[j].strip() and not _FENCE.match(lines[j]) and not _HEADING.match(lines[j])
               and lines[j].lstrip().startswith("|") == is_table):
            j += 1
        blocks.append(_Block("\n".join(lines[i:j]), "table" if is_table else "text", i + 1, j, path()))
        i = j
    return blocks


def _split_block(block: _Block) -> list[_Block]:
    """Split an oversize block on line boundaries (tables repeat their header rows)."""
    lines = block.text.split("\n")
    prefix = lines[:2] if block.kind == "table" and len(lines) > 3 else []
    prefix_tokens = sum(count_tokens(p) for p in prefix)
    pieces: list[_Block] = []
    cur: list[str] = []
    cur_start = cur_end = block.start + len(prefix)
    tokens = prefix_tokens

    for offset in range(len(prefix), len(lines)):
        line_no = block.start + offset
        for part in _split_long_line(lines[offset]):
            t = count_tokens(part)
            if cur and tokens + t > CHUNK_TARGET_TOKENS:
                pieces.append(_Block("\n".join(prefix + cur), block.kind, cur_start, cur_end, block.path))
                cur, cur_start, tokens = [], line_no, prefix_tokens
            cur.append(part)
            cur_end = line_no
            tokens += t
    if cur:
        pieces.append(_Block("\n".join(prefix + cur), block.kind, cur_start, cur_end, block.path))
    return pieces


def _split_long_line(line: str) -> list[str]:
    """A single line over the target is cut into overlapping word windows."""
    if count_tokens(line) <= CHUNK_TARGET_TOKENS:
        return [line]
    parts: list[str] = []
    cur: list[str] = []
    tokens = 0
    for word in line.split(" "):
        t = count_tokens(word)
        if cur and tokens + t > CHUNK_TARGET_TOKENS:
            parts.append(" ".join(cur))
            keep: list[str] = []
            kept = 0
            for w in reversed(cur):
                kept += count_tokens(w)
                if kept > CHUNK_OVERLAP_TOKENS:
                    break
                keep.insert(0, w)
            cur, tokens = keep, sum(count_tokens(w) for w in keep)
        cur.append(word)
        tokens += t
    if cur:
        parts.append(" ".join(cur))
    return parts


def _pack(blocks: list[_Block]) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    cur: list[_Block] = []
    tokens = 0

    def flush() -> None:
        """Emit the current chunk; a trailing heading is carried over so it never ends a chunk."""
        nonlocal cur, tokens
        carry: list[_Block] = []
        if len(cur) > 1 and cur[-1].kind == "heading":
            carry = [cur.pop()]
        if cur:
            chunks.append(_make(cur))
        cur = carry
        tokens = sum(count_tokens(b.text) for b in carry)

    for block in blocks:
        t = count_tokens(block.text)
        if cur and tokens + t > CHUNK_TARGET_TOKENS:
            flush()
        elif cur and block.kind == "heading" and tokens >= CHUNK_MIN_TOKENS:
            flush()
        cur.append(block)
        tokens += t
    if cur:
        chunks.append(_make(cur))

    # fold a tiny last chunk into its predecessor when it fits
    if len(chunks) > 1 and count_tokens(chunks[-1].text) < CHUNK_MIN_TOKENS:
        a, b = chunks[-2], chunks[-1]
        if count_tokens(a.text) + count_tokens(b.text) <= CHUNK_MAX_TOKENS:
            chunks[-2:] = [RawChunk(a.text + "\n\n" + b.text, a.start, b.end, a.heading_path,
                                    a.kind if a.kind == b.kind else "text")]
    return chunks


def _make(blocks: list[_Block]) -> RawChunk:
    kinds = {b.kind for b in blocks if b.kind != "heading"}
    kind = kinds.pop() if len(kinds) == 1 else "text"
    return RawChunk("\n\n".join(b.text for b in blocks), blocks[0].start, blocks[-1].end, blocks[0].path, kind)
