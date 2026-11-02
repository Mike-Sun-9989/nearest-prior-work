"""Tool names and descriptions shown to the user's agent. All retrieval runs locally."""
from .sections import SECTION_HELP

INDEX_BLURB = (
    "a section-level index of about 10,400 articles published 1996-2026 in Academy of Management Journal, Academy of "
    "Management Review, Administrative Science Quarterly, Journal of Management, Management Science, Organization Science "
    "and Strategic Management Journal")
SECTION_LIST = "; ".join(f"{k} = {v}" for k, v in SECTION_HELP.items())

INSTRUCTIONS = (
    f"Nearest Prior Work searches {INDEX_BLURB}. Each article is indexed separately by section ({SECTION_LIST}), so a "
    "theory passage is matched against theory sections and a method passage against method sections. Results contain only "
    "article metadata (DOI, title, journal, year), section names and similarity scores; no abstracts and no article "
    "text. The year is the year of first publication, often the online-first year. "
    "Workflow. For a passage or one section, call find_similar_articles. For a whole manuscript file, call "
    "outline_manuscript (when the file tools are available): it returns the numbered paragraphs, and you mark where each "
    "section starts, the way the index's articles were marked; then call find_similar_to_manuscript with file_path and "
    "your structure. When you report back, list the articles with year and journal, say which section matched "
    "best and how strong the match is (rank, percentile and z). Do not describe what an article argues or finds: the "
    "index returns only titles and scores, so anything beyond the title is not something the tool has shown you.")

FIND_SIMILAR_ARTICLES = (
    f"Find published articles most similar to a passage, a single section, or an indexed article, in {INDEX_BLURB}. "
    "Give `text` (any length; a paragraph is enough) and, when you know which part of a paper it is, `section` "
    f"(one of: {', '.join(SECTION_HELP)}). Always give the section when the passage clearly belongs to one (a hypothesis "
    "or argument is theory; data, sample, measures or estimation is method); results are more accurate. With a section, "
    "articles are ranked by that section only. Without one, the passage is compared with every section of every article "
    "and the best-matching section is reported. Or give `doi` "
    "of an article in the index to find its neighbours. Optional filters: `journals` (codes amj, amr, asq, jom, ms, os, "
    "smj or full names), `year_min`, `year_max`. Returns up to `k` articles (default 10, max 50) with DOI, title, journal, "
    "year, best_matching_section and per-section rank, percentile and z against random article pairs. "
    "For DOI queries, use `rank_by` with a section name to retrieve that section's nearest articles across the full eligible index.")

FIND_SIMILAR_TO_MANUSCRIPT = (
    "Find published articles most similar to a whole manuscript, compared section by section (abstract with abstract, "
    "theory with theory, method with method, and so on) and ranked by the mean z over the sections both papers have. "
    "Each result also reports per-section percentiles and the best-matching section, so you can tell papers that share "
    "a theory from papers that share a method. Pass the manuscript's sections as `sections_text`, an object whose keys "
    f"are section names ({', '.join(s for s in SECTION_HELP if s != 'body')}) and whose values are the full text of "
    "each section. Leave out references, tables and appendices. Same filters and `k` as find_similar_articles. "
    "Optionally set `rank_by` to a submitted section name to retrieve by that section across the full eligible index; "
    "the default is overall similarity.")

FILE_ARGS = (
    " Instead of `sections_text` you can pass `file_path` to a manuscript on this computer (.docx, .pdf, .md, .tex or "
    ".txt) together with `structure`, the section starts you marked on outline_manuscript's numbered paragraphs: "
    "{\"paper_type\": ..., \"title_par\": n or null, \"sections\": [{\"start\": n, \"heading\": ... or null, "
    "\"label\": ..., \"level\": 1 or 2}, ...]}. The sections are cut from the file's own paragraphs on this computer "
    "and mapped to the index sections with the rules used to build the index (front matter, references, appendices and "
    "notes are left out); only those sections are compared locally. The response lists which paragraphs went into "
    "each section.")

OUTLINE_MANUSCRIPT = (
    "Read a manuscript file on this computer (.docx, .pdf, .md, .tex or .txt) and return its numbered paragraphs (PDFs "
    "are read column by column, without running headers, page numbers or table cells), with instructions for marking "
    "its structure. The file is read locally and its numbered paragraphs are returned to your agent. Mark the paper type and where each section starts, then pass that as "
    "`structure` to find_similar_to_manuscript with the same file_path. Long files come in pages: call again with "
    "`start` = next_start until next_start is absent.")

GET_ARTICLE = "Look up one indexed article by DOI. Returns title, journal, year and which sections are indexed for it."
