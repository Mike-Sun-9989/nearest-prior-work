import pytest

from nearest_prior_work.manuscript import outline, sections_from_file
from nearest_prior_work.sections import canon, classify_heading

BODY = "word " * 200

MD = f"""Title of a working paper

Abstract: We study how firms learn. {BODY}

# 1. Introduction
{BODY}
# 2. Status and Learning in Alliances
{BODY}
## 2.1 Hypothesis development
{BODY}
# 3. Data and Methods
{BODY}
## 3.1 Robustness checks
{BODY}
# 4. Results
{BODY}
# 5. Discussion
{BODY}
# References
Smith, J. 2001. A paper.
"""


@pytest.mark.parametrize("h,s", [("1. Introduction", "introduction"), ("THEORY AND HYPOTHESES", "theory"),
                                 ("Literature Review", "theory"), ("3 Data and Methods", "method"),
                                 ("Empirical Setting", "method"), ("Results", "results"), ("Robustness Checks", "robustness"),
                                 ("Additional Analyses", "robustness"), ("Discussion and Implications", "discussion"),
                                 ("Conclusion", "conclusion"), ("References", "skip"), ("Appendix A", "skip"),
                                 ("Status and Learning", None)])
def test_classify_heading(h, s):
    assert classify_heading(h) == s


def test_canon():
    assert canon("Methods") == "method" and canon("intro") == "introduction" and canon("funding") is None


def test_markdown_outline_and_mapping(tmp_path):
    p = tmp_path / "paper.md"
    p.write_text(MD, encoding="utf-8")
    info, _ = outline(str(p))
    sec = {r["heading"]: r["section"] for r in info["headings"]}
    assert sec["(text before the first heading)"] == "abstract"
    assert sec["Introduction"] == "introduction"
    assert sec["Status and Learning in Alliances"] == "theory"  # untitled theory section after the introduction
    assert sec["Hypothesis development"] == "theory"
    assert sec["Robustness checks"] == "robustness"
    assert sec["References"] == "not used"
    texts, used = sections_from_file(str(p))
    assert set(texts) == {"abstract", "introduction", "theory", "method", "robustness", "results", "discussion"}
    assert "Smith" not in " ".join(texts.values())
    assert texts["abstract"].startswith("We study")


def test_section_headings_override(tmp_path):
    p = tmp_path / "paper.md"
    p.write_text(MD, encoding="utf-8")
    texts, used = sections_from_file(str(p), {"theory": [2, 3], "method": 4})
    assert set(texts) == {"theory", "method"}
    assert used["theory"]["headings"][0].startswith("2.")
    with pytest.raises(ValueError):
        sections_from_file(str(p), {"theory": [99]})
    with pytest.raises(ValueError):
        sections_from_file(str(p), {"funding": [1]})


def test_plain_text_and_docx(tmp_path):
    txt = tmp_path / "paper.txt"
    txt.write_text(f"INTRODUCTION\n{BODY}\n\nTHEORETICAL BACKGROUND\n{BODY}\n\nMETHODS\n{BODY}\n", encoding="utf-8")
    texts, _ = sections_from_file(str(txt))
    assert set(texts) == {"introduction", "theory", "method"}

    import docx
    d = docx.Document()
    d.add_heading("A title", 0)
    d.add_paragraph("Abstract. " + BODY)
    d.add_heading("Introduction", 1)
    d.add_paragraph(BODY)
    d.add_heading("Methods", 1)
    d.add_paragraph(BODY)
    p = tmp_path / "paper.docx"
    d.save(str(p))
    info, _ = outline(str(p))
    assert info["words_by_section"].get("introduction") == 200 and info["words_by_section"].get("method") == 200


def test_missing_and_unsupported(tmp_path):
    with pytest.raises(FileNotFoundError):
        outline(str(tmp_path / "nope.docx"))
    (tmp_path / "x.rtf").write_text("x")
    with pytest.raises(ValueError):
        outline(str(tmp_path / "x.rtf"))
