"""
Read a manuscript on the user's computer, split it at its headings, and map headings to index sections.

Everything here runs locally. The agent sees only the outline (headings, word counts, proposed sections); the text of the
sections it chooses is sent to the server for encoding and is not stored there.
"""
import os
import re

from .sections import SECTIONS, canon, classify_heading, strip_number

SUPPORTED = (".docx", ".pdf", ".md", ".markdown", ".tex", ".txt")
_END_PUNCT = re.compile(r"[.,;:]$")
_NUMBERED = re.compile(r"^\s*(\d+(\.\d+)*)\.?\s+\S")
_ROMAN = re.compile(r"^\s*[IVX]+\.\s+\S")


class Block:
    def __init__(self, bid, heading, level):
        self.id, self.heading, self.level, self.lines, self.section = bid, heading, level, [], None

    @property
    def text(self):
        return "\n".join(self.lines).strip()

    @property
    def words(self):
        return len(self.text.split())


def _plain_heading(line):
    """Heading level for a line of plain text (txt, pdf), or None when it does not look like a heading."""
    s = line.strip()
    if not s or len(s) > 120:
        return None
    w = s.split()
    if len(w) > 12 or _END_PUNCT.search(s) or not re.search(r"[A-Za-z]", s):
        return None
    m = _NUMBERED.match(s)
    if m:
        if not re.match(r"^\s*[\d.]+\s+[A-Z]", s):
            return None
        return min(3, m.group(1).count(".") + 1)
    c = classify_heading(s)
    letters = re.sub(r"[^A-Za-z]", "", s)
    if c is not None and len(w) <= 8 and (s[0].isupper() or s.isupper()):
        return 1
    if _ROMAN.match(s) or (letters.isupper() and len(letters) >= 4):
        return 1
    return None


def _read_docx(path):
    import docx
    d = docx.Document(path)
    out = []
    for p in d.paragraphs:
        t = p.text.strip()
        if not t:
            continue
        st = (p.style.name or "").lower() if p.style is not None else ""
        lvl = None
        m = re.match(r"heading (\d)", st)
        if m:
            lvl = int(m.group(1))
        elif st == "title":
            lvl = 0
        else:
            bold = p.runs and all((r.bold or (r.style is not None and r.style.font.bold)) for r in p.runs if r.text.strip())
            if bold and len(t.split()) <= 12 and not _END_PUNCT.search(t):
                lvl = _plain_heading(t) or 2
            elif len(t.split()) <= 8:
                lvl = _plain_heading(t)
        out.append((t, lvl))
    return out


def _read_md(path):
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        m = re.match(r"^(#{1,6})\s+(.*)$", line.rstrip())
        out.append((m.group(2).strip(), len(m.group(1))) if m else (line.rstrip(), None))
    return out


def _read_tex(path):
    src = open(path, encoding="utf-8", errors="replace").read()
    src = re.sub(r"(?<!\\)%.*", "", src)
    src = re.sub(r"\\begin\{abstract\}", "\n\\\\section{Abstract}\n", src)
    src = re.sub(r"\\end\{abstract\}", "\n", src)
    src = re.sub(r"\\(begin|end)\{(document|thebibliography)\}.*", "", src)
    out = []
    for line in src.splitlines():
        m = re.match(r"^\s*\\(section|subsection|subsubsection)\*?\{(.*)\}", line)
        if m:
            out.append((m.group(2).strip(), {"section": 1, "subsection": 2, "subsubsection": 3}[m.group(1)]))
            continue
        line = re.sub(r"\\(cite[tp]?|ref|label|eqref)\{[^}]*\}", "", line)
        line = re.sub(r"\\[a-zA-Z]+\*?(\[[^\]]*\])?", "", line).replace("{", "").replace("}", "")
        out.append((line, None))
    return out


def _read_pdf(path):
    from pypdf import PdfReader
    out = []
    for page in PdfReader(path).pages:
        for line in (page.extract_text() or "").splitlines():
            out.append((line, _plain_heading(line)))
    return out


def _read_txt(path):
    return [(line.rstrip(), _plain_heading(line)) for line in open(path, encoding="utf-8", errors="replace")]


def read_lines(path):
    path = os.path.expanduser(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED:
        raise ValueError(f"unsupported file type {ext}; use one of {', '.join(SUPPORTED)} (or paste the text)")
    return {".docx": _read_docx, ".pdf": _read_pdf, ".md": _read_md, ".markdown": _read_md, ".tex": _read_tex,
            ".txt": _read_txt}[ext](path)


def split_blocks(lines):
    """Block 0 holds everything before the first heading (title page, often the abstract)."""
    blocks = [Block(0, "(text before the first heading)", 0)]
    for text, lvl in lines:
        if lvl == 0 and len(blocks) == 1:  # a Word "Title" paragraph stays in the front matter
            blocks[0].heading = f"(title page) {text.strip()}"
        elif lvl is not None:
            blocks.append(Block(len(blocks), text.strip(), max(1, lvl)))
        else:
            blocks[-1].lines.append(text)
    return blocks


def auto_map(blocks):
    """Assign an index section (or None / 'skip') to every block from its heading and position."""
    top = None
    for b in blocks:
        c = classify_heading(b.heading) if b.id else None
        if top is None and c is None:
            # Front matter or a title heading before the body: pick up an "Abstract" paragraph if there is one.
            m = re.search(r"(?im)^\s*abstract\b[:.\s]*", b.text)
            if m:
                b.lines = [b.text[m.end():]]
                b.section = "abstract"
            continue
        if b.level <= 1:
            if c is None:
                c = "theory" if top in ("introduction", "theory") else top
            top = c
            b.section = c
        else:
            if c == "skip":
                b.section = "skip"
            elif c == "robustness" or (c and top in (None, "skip")):
                b.section = c
            else:
                b.section = top
    if not any(b.section == "introduction" for b in blocks):
        # No "Introduction" heading: many manuscripts open the body right after the abstract.
        first = next((b for b in blocks if b.id > 0), None)
        if first is not None and first.section is None and first.words > 150:
            first.section = "introduction"
    return blocks


def outline(path, with_text=False):
    """with_text adds each block's text to its row (the web page maps sections itself and sends the text back)."""
    blocks = auto_map(split_blocks(read_lines(path)))
    rows = [{"n": b.id, "heading": strip_number(b.heading) if b.id else b.heading, "level": b.level, "words": b.words,
             "section": b.section if b.section in SECTIONS else ("not used" if b.section == "skip" else None),
             **({"text": b.text} if with_text else {})}
            for b in blocks if b.id == 0 or b.words or b.heading]
    totals = {}
    for b in blocks:
        if b.section in SECTIONS:
            totals[b.section] = totals.get(b.section, 0) + b.words
    return {"file": os.path.abspath(os.path.expanduser(path)), "headings": rows, "words_by_section": totals,
            "unmapped_words": sum(b.words for b in blocks if b.section is None)}, blocks


def sections_from_file(path, section_headings=None):
    """Return ({section: text}, {section: {"headings": [...], "words": n}}) for a manuscript file."""
    info, blocks = outline(path)
    by_id = {b.id: b for b in blocks}
    if section_headings:
        assign = {}
        for key, ids in section_headings.items():
            s = canon(key)
            if s is None:
                raise ValueError(f"unknown section {key!r}; use one of {SECTIONS}")
            for i in ([ids] if isinstance(ids, int) else ids):
                if int(i) not in by_id:
                    raise ValueError(f"no heading number {i} in the outline")
                assign[int(i)] = s
    else:
        assign = {b.id: b.section for b in blocks if b.section in SECTIONS}
    texts, used = {}, {}
    for i in sorted(assign):
        s, b = assign[i], by_id[i]
        if not b.text:
            continue
        texts[s] = (texts.get(s, "") + "\n\n" + b.text).strip()
        u = used.setdefault(s, {"headings": [], "words": 0})
        u["headings"].append(f"{i}. {strip_number(b.heading) if i else b.heading}")
        u["words"] += b.words
    if not texts:
        raise ValueError("no section could be identified in this file; call outline_manuscript and pass section_headings, "
                         "or pass sections_text directly")
    return texts, used
