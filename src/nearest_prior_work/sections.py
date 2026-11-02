"""Canonical section names shared by the client and the server, and the heading classifier used for manuscripts."""
import re

SECTIONS = ["abstract", "introduction", "theory", "method", "results", "robustness", "discussion", "conclusion", "body"]

SECTION_HELP = {
    "abstract": "abstract",
    "introduction": "introduction",
    "theory": "theory, literature review, hypotheses or propositions",
    "method": "data, sample, measures, research design and estimation",
    "results": "results or findings",
    "robustness": "robustness checks and additional analyses",
    "discussion": "discussion, implications and limitations",
    "conclusion": "conclusion",
    "body": "full text of articles without standard sections (a few essays)",
}

ALIASES = {
    "intro": "introduction", "introductions": "introduction",
    "theories": "theory", "theoretical": "theory", "hypotheses": "theory", "literature": "theory", "lit": "theory",
    "methods": "method", "methodology": "method", "data": "method", "design": "method",
    "result": "results", "findings": "results",
    "robust": "robustness", "robustness checks": "robustness",
    "discussions": "discussion", "conclusions": "conclusion",
}


def canon(name):
    """Map a user-supplied section name to a canonical one, or None."""
    if name is None:
        return None
    x = str(name).strip().lower()
    if x in SECTIONS:
        return x
    return ALIASES.get(x)


# Heading -> section. Order matters: the first matching rule wins.
_SKIP = re.compile(r"^(references|bibliography|works cited|literature cited|appendi(x|ces)|online appendix|supplement|"
                   r"tables?\b|figures?\b|acknowledg|notes\b|endnotes|footnotes|author (bio|note)|about the author|"
                   r"funding|declaration|conflicts? of interest|data availability)", re.I)
_RULES = [
    ("abstract", r"^abstract\b"),
    ("introduction", r"^introduction\b|^intro\b"),
    ("robustness", r"robust|additional analys|supplementa(l|ry) analys|sensitivity analys|alternative (explanation|specification)|endogeneity"),
    ("conclusion", r"^conclu|concluding|^summary and conclu"),
    ("discussion", r"^discussion|general discussion|implications|limitations|future research"),
    ("results", r"^results?\b|findings|^empirical results|^analys[ie]s and results|^main results"),
    ("method", r"method|^data\b|data and|^sample|research design|empirical (strategy|setting|approach|context|design)|"
               r"^(research )?setting|^measures?\b|^variables\b|estimation|model specification|identification strategy|"
               r"^study \d|^experiment \d|^the (data|sample)"),
    ("theory", r"theor|hypothes|literature|background|conceptual|framework|prior (research|work)|related (work|research)|"
               r"propositions?\b|^model\b"),
]
_RULES = [(s, re.compile(p, re.I)) for s, p in _RULES]
_NUM = re.compile(r"^\s*((\d+(\.\d+)*|[ivxlcdm]+|[A-H])[.)]?\s+)", re.I)


def strip_number(heading):
    return _NUM.sub("", heading or "").strip()


def classify_heading(heading):
    """Return a canonical section for a heading, 'skip' for back matter, or None when the heading says nothing."""
    h = strip_number(heading)
    if not h:
        return None
    if _SKIP.match(h):
        return "skip"
    for s, rx in _RULES:
        if rx.search(h):
            return s
    return None
