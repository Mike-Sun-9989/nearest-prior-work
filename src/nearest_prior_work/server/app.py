"""Local application entry point and shared request limits."""
from .web import build_local_app

SIMILAR_ARGS = {"text", "section", "sections_text", "doi", "k", "journals", "year_min", "year_max", "rank_by"}
PAGE_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
