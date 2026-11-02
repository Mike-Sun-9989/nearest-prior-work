"""
Numbered paragraphs of a manuscript, the input the language model reads to find its sections (see structure.py).

Every format becomes a list of {"kind", "text"} items, where kind is H (looks like a heading), P (paragraph), CAP (table or
figure caption) or FN (footnote or other small print). The kinds are hints only: the model decides where sections start.

PDFs are read with pdfplumber: words are grouped into columns and lines, running headers, footers and page numbers are
removed, lines that are mostly numbers (table cells) are dropped, and lines are joined into paragraphs by spacing,
indentation and font. Word, Markdown, LaTeX and plain text keep their own paragraphs and heading styles.
"""
import os
import re
from collections import Counter

from .manuscript import SUPPORTED, _plain_heading

_CAPTION = re.compile(r"^\s*(table|figure|fig\.|exhibit|chart|panel)\s+[A-Z]?\d+[A-Za-z]?\b", re.I)
_SENT_END = re.compile(r"[.?!:;)\"”’]$")
_BOLD = re.compile(r"bold|black|heavy|semibold|demi|,b$|-b$|\.b$", re.I)
_NUM = re.compile(r"^[\(\[]?[-−–+]?[\d.,]+%?[\)\]*†‡]*$|^[*†‡]+$")
MAX_PARAGRAPHS = 3000


def _item(kind, text):
    return {"kind": kind, "text": re.sub(r"\s+", " ", text).strip()}


# ------------------------------------------------------------------ PDF
def _rows(words, tol=2.5):
    """Words grouped into rows across the whole page width (top within `tol` points)."""
    rows = []
    for w in sorted(words, key=lambda w: w["top"]):
        if rows and w["top"] - rows[-1][0]["top"] <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def _columns(words, width):
    """x position of the gutter between two columns, or None for a one-column page. A page has two columns when many
    rows have words on both sides of the same empty vertical band; rows that cross it (title, abstract) are full width."""
    rows = [r for r in _rows(words) if len(r) >= 3]
    if len(rows) < 12:
        return None
    best = (0, None, 0)
    for x in range(int(width * 0.3), int(width * 0.7)):
        n = c = 0
        for r in rows:
            if any(w["x0"] < x + 3 and w["x1"] > x - 3 for w in r):
                c += 1
            elif any(w["x1"] <= x - 3 for w in r) and any(w["x0"] >= x + 3 for w in r):
                n += 1
        if n > best[0]:
            best = (n, [x], c)
        elif n == best[0] and best[1] and x == best[1][-1] + 1:
            best[1].append(x)  # plateau: take its middle
    # Left and right lines are often not at the same height, so many rows hold one column only: compare the rows with
    # a gap at x with the rows that cross x (a one-column page has almost no rows with a gap at the same x).
    if best[0] < 8 or best[0] < best[2] * 0.5:
        return None
    return (best[1][0] + best[1][-1]) / 2


def _lines(words, col):
    """Group the words of one column into lines (top within 3 points), left to right."""
    out = [{"top": min(w["top"] for w in r), "words": sorted(r, key=lambda w: w["x0"]), "col": col}
           for r in _rows(words, tol=3)]
    for L in out:
        ws = L["words"]
        L["text"] = " ".join(w["text"] for w in ws)
        L["x0"], L["x1"] = min(w["x0"] for w in ws), max(w["x1"] for w in ws)
        L["bottom"] = max(w["bottom"] for w in ws)
        n = sum(len(w["text"]) for w in ws) or 1
        L["size"] = sorted(w["size"] for w in ws)[len(ws) // 2]
        L["bold"] = sum(len(w["text"]) for w in ws if _BOLD.search(w["fontname"].split("+")[-1])) / n
    return out


def _page_lines(page):
    W = float(page.width)
    words = [w for w in page.extract_words(x_tolerance=1.5, y_tolerance=2, keep_blank_chars=False, use_text_flow=False,
                                           extra_attrs=["fontname", "size", "upright"])
             if w["upright"] and w["size"] >= 4 and 0 <= w["x0"] and w["x1"] <= W + 1]
    g = _columns(words, W)
    if g is None:
        return _lines(words, 0)
    span, left, right = [], [], []
    for r in _rows(words):
        if any(w["x0"] < g + 3 and w["x1"] > g - 3 for w in r):
            span += r  # a full-width row (title, abstract, wide table) stays whole
        else:
            left += [w for w in r if w["x1"] <= g]
            right += [w for w in r if w["x0"] >= g]
    sp = sorted(_lines(span, -1), key=lambda L: L["top"])
    cols = _lines(left, 0) + _lines(right, 1)
    # Reading order: bands separated by full-width rows of body text (title, abstract, a full-width passage); inside a
    # band the left column, then the right one. Full-width tables, figures and captions do not split the columns (the
    # text flows around them) and go to the end of the page.
    med = sorted(w["size"] for w in words)[len(words) // 2]

    def is_float(L):
        toks = L["text"].split()
        return (L["size"] < med - 0.5 or _CAPTION.match(L["text"]) is not None
                or (len(toks) >= 3 and sum(bool(_NUM.match(x)) for x in toks) / len(toks) >= 0.3))
    floats = [L for L in sp if is_float(L)]
    sep = [L for L in sp if not is_float(L)]
    tops = [L["top"] for L in sep]

    def band(t):
        return sum(1 for x in tops if x < t - 1)
    keyed = [((band(L["top"]), L["col"], L["top"]), L) for L in cols] + [((i, 2, L["top"]), L) for i, L in enumerate(sep)]
    return [L for _, L in sorted(keyed, key=lambda kv: kv[0])] + floats


def _norm_running(text):
    return re.sub(r"[\d\s|·•.,–—-]+", " ", text.lower()).strip()


def read_pdf_paragraphs(path):
    import pdfplumber
    pages = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            pages.append((float(p.height), _page_lines(p)))
    if not pages:
        return []
    # Running headers and footers: lines near the top or bottom whose text (without numbers) repeats across pages.
    edge = Counter()
    for H, lines in pages:
        seen = {_norm_running(L["text"]) for L in lines if L["top"] < H * 0.1 or L["bottom"] > H * 0.9}
        edge.update(s for s in seen if s)
    repeat = max(2, int(len(pages) * 0.25))
    body_size = Counter(round(L["size"]) for _, lines in pages for L in lines
                        for _ in range(len(L["text"]))).most_common(1)[0][0]
    flat = []
    for pi, (H, lines) in enumerate(pages):
        for L in lines:
            near_edge = L["top"] < H * 0.1 or L["bottom"] > H * 0.9
            t = L["text"].strip()
            if near_edge and (edge[_norm_running(t)] >= repeat or re.fullmatch(r"(page\s*)?\d{1,4}", t, re.I)):
                continue
            toks = t.split()
            if len(toks) >= 3 and sum(bool(_NUM.match(x)) for x in toks) / len(toks) >= 0.5:
                continue  # table row
            L["page"] = pi
            flat.append(L)
    gaps = sorted(b["top"] - a["bottom"] for a, b in zip(flat, flat[1:])
                  if a["page"] == b["page"] and a["col"] == b["col"] and 0 <= b["top"] - a["bottom"] < 20)
    gap = gaps[len(gaps) // 2] if gaps else 2.0
    lefts = Counter((L["page"], L["col"], round(L["x0"])) for L in flat)

    def kind(L):
        t = L["text"]
        if _CAPTION.match(t):
            return "CAP"
        if L["size"] < body_size - 1.2:
            return "FN"
        words = t.split()
        if len(words) <= 15 and not re.search(r"[.,;]$", t) and (L["bold"] >= 0.8 or L["size"] >= body_size + 1):
            return "H"
        return "P"

    out, cur, prev = [], None, None
    for L in flat:
        k = kind(L)
        new = cur is None or k != cur["kind"] or k == "H" and prev is not None and L["top"] - prev["bottom"] > gap * 3
        if not new and prev is not None:
            same_flow = prev["page"] == L["page"] and prev["col"] == L["col"]
            if same_flow:
                if L["top"] - prev["bottom"] > gap * 2.2 + 1:
                    new = True
                elif k == "P" and L["x0"] > prev["x0"] + 6 and lefts[(L["page"], L["col"], round(prev["x0"]))] > 3:
                    new = True  # first-line indent
            elif _SENT_END.search(prev["text"]) and not prev["text"].endswith(("-", "‐")):
                new = True  # a column or page ends on a full sentence: start a new paragraph
        if new:
            cur = {"kind": k, "lines": [L["text"]]}
            out.append(cur)
        else:
            last = cur["lines"][-1]
            if re.search(r"[A-Za-z][-‐]$", last) and L["text"][:1].islower():
                cur["lines"][-1] = last[:-1] + L["text"]  # hyphenated line break
            else:
                cur["lines"].append(L["text"])
        prev = L
    raw = [it for it in (_item(p["kind"], " ".join(p["lines"])) for p in out) if it["text"]]
    for i, it in enumerate(raw):
        nxt = raw[i + 1] if i + 1 < len(raw) else None
        if it["kind"] == "H" and (len(it["text"].split()) > 25 or it["text"][:1].islower()
                                  or (nxt and nxt["kind"] == "P" and nxt["text"][:1].islower()
                                      and not _SENT_END.search(it["text"]))):
            it["kind"] = "P"  # bold body text (some journals set the abstract in bold), not a heading
    items = []
    for it in raw:
        prev = items[-1] if items else None
        if (prev and it["kind"] == "P" and prev["kind"] == "P" and it["text"][:1].islower()
                and not _SENT_END.search(prev["text"])):
            prev["text"] += " " + it["text"]  # a paragraph cut by a column, page, float or font change
        else:
            items.append(it)
    return items


# ------------------------------------------------------------------ other formats
def _blocks(lines):
    """Join (text, level) lines into paragraphs at blank lines; heading lines become their own item."""
    out, buf = [], []
    def flush():
        if buf:
            t = " ".join(buf)
            out.append(_item("CAP" if _CAPTION.match(t) else "P", t))
            buf.clear()
    for text, lvl in lines:
        if lvl is not None:
            flush()
            out.append(_item("H", text))
        elif not text.strip():
            flush()
        else:
            buf.append(text.strip())
    flush()
    return out


def read_docx_paragraphs(path):
    import docx
    d = docx.Document(path)
    out = []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        st = (p.style.name or "").lower() if p.style is not None else ""
        if re.match(r"heading \d|title|subtitle", st):
            k = "H"
        elif st == "caption" or _CAPTION.match(t):
            k = "CAP"
        else:
            runs = [r for r in p.runs if r.text.strip()]
            bold = runs and all(r.bold or (r.style is not None and r.style.font.bold) for r in runs)
            k = "H" if bold and len(t.split()) <= 15 and not re.search(r"[.,;]$", t) else "P"
        out.append(_item(k, t))
    return out


def read_paragraphs(path):
    """[{kind, text}] for a manuscript file; raises ValueError for an unsupported type."""
    from .manuscript import _read_md, _read_tex
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported file type {ext}; use one of {', '.join(SUPPORTED)} (or paste the text)")
    if ext == ".pdf":
        out = read_pdf_paragraphs(path)
    elif ext == ".docx":
        out = read_docx_paragraphs(path)
    elif ext in (".md", ".markdown"):
        out = _blocks(_read_md(path))
    elif ext == ".tex":
        out = _blocks(_read_tex(path))
    else:
        raw = open(path, encoding="utf-8", errors="replace").read()
        if "\n\n" not in raw.strip():  # no blank lines: one paragraph per line
            raw = raw.replace("\n", "\n\n")
        out = _blocks([(L.rstrip(), _plain_heading(L) if len(L.split()) <= 12 and L.strip() else None)
                       for L in raw.splitlines()])
    out = [p for p in out if p["text"]]
    if not out:
        raise ValueError("no text could be read from this file (a scanned PDF needs OCR first)")
    if len(out) > MAX_PARAGRAPHS:
        raise ValueError(f"the file has {len(out):,} paragraphs (max {MAX_PARAGRAPHS:,}); send the main text only")
    return out
