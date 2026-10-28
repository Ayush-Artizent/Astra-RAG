"""Section-aware markdown chunking: one chunk per heading section, each with its own heading path.
Code fences and tables are kept whole where they fit; an oversize section is split on block/line boundaries."""
import re
from dataclasses import dataclass, field

from ...config import CHUNK_MAX_TOKENS, CHUNK_MIN_TOKENS, CHUNK_OVERLAP_TOKENS, CHUNK_TARGET_TOKENS
from .tokens import count_tokens

_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")  # horizontal rule: --- *** ___


def _is_rule(line: str) -> bool:
    return _RULE.match(line) is not None


@dataclass
class RawChunk:
    text: str
    start: int | None      # 1-based line range in the source text
    end: int | None
    heading_path: tuple[str, ...]
    kind: str              # text | table | code | csv_row | csv_summary
    extra: dict = field(default_factory=dict)


@dataclass
class _Block:
    text: str
    kind: str              # heading | text | table | code
    start: int
    end: int
    path: tuple[str, ...]


def chunk_markdown(text: str) -> list[RawChunk]:
    chunks: list[RawChunk] = []
    for section in _sections(_parse_blocks(text)):
        if len(section) == 1 and section[0].kind == "heading":
            continue  # heading with no body of its own: its children carry it in their heading path
        blocks: list[_Block] = []
        for block in section:
            blocks.extend(_split_block(block) if count_tokens(block.text) > CHUNK_MAX_TOKENS else [block])
        chunks.extend(_pack(blocks))
    if not chunks and text.strip():  # e.g. a file that is only headings
        chunks.append(RawChunk(text.strip(), 1, len(text.splitlines()), (), "text"))
    return chunks


def _sections(blocks: list[_Block]) -> list[list[_Block]]:
    """Group blocks into sections: a section starts at every heading (text before the first heading is its own)."""
    sections: list[list[_Block]] = []
    for block in blocks:
        if block.kind == "heading" or not sections:
            sections.append([])
        sections[-1].append(block)
    return sections


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
        if _is_rule(line):  # decoration, not content: omitted (line numbers still count it)
            i += 1
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
        # a `---` straight under a text line is a setext underline and stays; `***` / `___` end the run
        while (j < n and lines[j].strip() and not _FENCE.match(lines[j]) and not _HEADING.match(lines[j])
               and not (_is_rule(lines[j]) and lines[j].strip()[0] != "-")
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
    """Pack one section's blocks into chunks of ~target size (a lone heading is never cut off from its body)."""
    chunks: list[RawChunk] = []
    cur: list[_Block] = []
    tokens = 0
    for block in blocks:
        t = count_tokens(block.text)
        if cur and tokens + t > CHUNK_TARGET_TOKENS and not (len(cur) == 1 and cur[0].kind == "heading"):
            chunks.append(_make(cur))
            cur, tokens = [], 0
        cur.append(block)
        tokens += t
    if cur:
        chunks.append(_make(cur))

    # fold a tiny last piece into its predecessor when it fits
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
