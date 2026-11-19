import re
from collections.abc import Callable

from tarot.ingest.parse import ParsedDocument
from tarot.schemas import Chunk, ChunkingVariant, Span

SEPARATORS = ("\n\n", "\n", ". ", " ")
DEFINED_RES = (
    re.compile(r"\((?:the |each |collectively, the )?[\"“]([A-Z][^\"“”]{1,60})[\"”]\)"),
    re.compile(r"[\"“]([A-Z][^\"“”]{1,60})[\"”]\s+(?:shall\s+mean|means)"),
)


def qwen_token_counter() -> Callable[[str], int]:
    from tokenizers import Tokenizer

    tok = Tokenizer.from_pretrained("Qwen/Qwen3-Embedding-0.6B")
    return lambda s: len(tok.encode(s, add_special_tokens=False).ids)


def _units(text, start, end, count, max_tokens, level=0):
    if count(text[start:end]) <= max_tokens or level >= len(SEPARATORS):
        yield start, end
        return
    sep, pos = SEPARATORS[level], start
    while pos < end:
        i = text.find(sep, pos, end)
        cut = end if i < 0 else i + len(sep)
        yield from _units(text, pos, cut, count, max_tokens, level + 1)
        pos = cut


def _split(text, start, end, count, max_tokens) -> list[tuple[int, int]]:
    """Tile text[start:end] with pieces of at most max_tokens, preferring coarse separators."""
    pieces, cur_start, cur_end, cur_tokens = [], start, start, 0
    for s, e in _units(text, start, end, count, max_tokens):
        n = count(text[s:e])  # shortcut: summed per-unit counts approximate the joined count
        if cur_end > cur_start and cur_tokens + n > max_tokens:
            pieces.append((cur_start, cur_end))
            cur_start, cur_tokens = s, 0
        cur_end, cur_tokens = e, cur_tokens + n
    pieces.append((cur_start, cur_end))
    return pieces


def _trim(text: str, start: int, end: int) -> tuple[int, int] | None:
    piece = text[start:end]
    lead = len(piece) - len(piece.lstrip())
    return (start + lead, start + len(piece.rstrip())) if piece.strip() else None


def _defined_terms(text: str) -> set[str]:
    return {m[1] for rx in DEFINED_RES for m in rx.finditer(text)}


def chunk(
    parsed: ParsedDocument,
    variant: ChunkingVariant,
    count_tokens: Callable[[str], int],
    max_tokens: int = 512,
) -> list[Chunk]:
    if variant not in (ChunkingVariant.C0, ChunkingVariant.C1, ChunkingVariant.C2):
        raise ValueError(f"{variant} waits for E1 (Week 8)")
    text = parsed.text
    if variant == ChunkingVariant.C0:
        bounds = [(0, len(text), ())]
    else:
        starts = [h.span.start for h in parsed.headings]
        ends = [*starts[1:], len(text)]
        bounds = [(0, starts[0] if starts else len(text), ())]
        stack: list[tuple[int, str]] = []
        for h, end in zip(parsed.headings, ends, strict=False):
            while stack and stack[-1][0] >= h.level:
                stack.pop()
            stack.append((h.level, h.title))
            bounds.append((h.span.start, end, tuple(t for _, t in stack)))
    doc_type = parsed.document.title or "Certificate of Incorporation"
    defined = _defined_terms(text) if variant == ChunkingVariant.C2 else set()
    chunks = []
    for start, end, path in bounds:
        seg = _trim(text, start, end)
        if seg is None:
            continue
        for s, e in _split(text, *seg, count_tokens, max_tokens):
            if (span := _trim(text, s, e)) is None:
                continue
            body = text[span[0] : span[1]]
            header = ""
            if variant == ChunkingVariant.C2:
                header = " › ".join((doc_type, *(t.rstrip(".") for t in path)))
                if uses := sorted(t for t in defined if t in body)[:8]:
                    header += f". Uses: {', '.join(uses)}"
                header += "."
            chunks.append(
                Chunk.create(
                    document_id=parsed.document.document_id,
                    variant=variant,
                    span=Span(start=span[0], end=span[1]),
                    text=body,
                    section_path=path,
                    header=header,
                )
            )
    return chunks
