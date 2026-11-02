"""The local MCP client against an in-process server (no network)."""
import json

import anyio
import pytest
from starlette.testclient import TestClient

from nearest_prior_work.mcp_client import build_server
from nearest_prior_work.local import LocalClient
from conftest import FakeEncoder


@pytest.fixture()
def mcp(offline_db_dir):
    client = LocalClient(offline_db_dir, encoder=FakeEncoder())
    yield build_server(client), client


def call(server, name, args):
    res = anyio.run(lambda: server.call_tool(name, args))
    if isinstance(res, tuple):
        res = res[1] if isinstance(res[1], dict) else res[0]
    if hasattr(res, "structured_content") and res.structured_content:
        return res.structured_content
    if hasattr(res, "content"):
        res = res.content
    if isinstance(res, list):
        return json.loads(res[0].text)
    return res


def test_tools_listed(mcp):
    server, _ = mcp
    names = {t.name for t in anyio.run(server.list_tools)}
    assert names == {"find_similar_articles", "find_similar_to_manuscript", "outline_manuscript", "get_article"}


def test_passage_and_file(mcp, tmp_path):
    server, _ = mcp
    out = call(server, "find_similar_articles", {"text": "alliances and status " * 20, "k": 4})
    assert out["n_results"] == 4
    p = tmp_path / "m.md"
    p.write_text("# Introduction\n" + "a b c " * 100 + "\n# Theory\n" + "d e f " * 100 + "\n# References\nX\n")
    o = call(server, "outline_manuscript", {"file_path": str(p)})
    assert o["paragraphs_total"] == 6 and o["paragraphs"][0] == "[0] H Introduction" and "how_to_mark" in o
    assert o["paragraphs"][1].endswith("… (300 words)")  # long paragraphs show only their opening
    assert "structure" in call(server, "find_similar_to_manuscript", {"file_path": str(p)})["error"]
    structure = {"paper_type": "quantitative_empirical", "title_par": None, "sections": [
        {"start": 0, "heading": "Introduction", "label": "introduction", "level": 1},
        {"start": 2, "heading": "Theory", "label": "theory", "level": 1},
        {"start": 4, "heading": "References", "label": "references", "level": 1}]}
    out = call(server, "find_similar_to_manuscript", {"file_path": str(p), "structure": structure, "k": 3})
    assert out["query"]["mode"] == "manuscript" and set(out["query"]["sections_sent"]) == {"introduction", "theory"}
    assert out["query"]["sections_sent"]["theory"] == {"from": ["[2] Theory"], "words": 302}
    bad = {**structure, "sections": [{"start": 9, "label": "theory"}]}
    assert "out of range" in call(server, "find_similar_to_manuscript", {"file_path": str(p), "structure": bad})["error"]


def test_outline_pages(mcp, tmp_path):
    server, _ = mcp
    p = tmp_path / "long.md"
    p.write_text("\n\n".join(f"Paragraph {i} " + "word " * 300 for i in range(400)))
    o = call(server, "outline_manuscript", {"file_path": str(p)})
    nxt = o["next_start"]
    assert o["showing"] == [0, nxt - 1] and sum(len(x) for x in o["paragraphs"]) <= 40_000
    o2 = call(server, "outline_manuscript", {"file_path": str(p), "start": nxt})
    assert o2["paragraphs"][0].startswith(f"[{nxt}] P Paragraph {nxt} ")


def test_errors_are_returned_not_raised(mcp, tmp_path):
    server, bad = mcp
    assert "not found" in call(server, "outline_manuscript", {"file_path": str(tmp_path / "none.pdf")})["error"]
    assert "unknown section" in call(server, "find_similar_articles", {"text": "x", "section": "funding"})["error"]
    s2 = build_server(bad)
    assert "not in the index" in call(s2, "get_article", {"doi": "10.9999/missing"})["error"]


def test_mcp_accepts_section_retrieval(mcp):
    server, _ = mcp
    out = call(server, 'find_similar_articles', {'doi': '10.9999/test.12', 'rank_by': 'theory', 'k': 3})
    assert out['query']['rank_by'] == 'theory'
    out = call(server, 'find_similar_to_manuscript', {
        'sections_text': {'theory': 'theory text', 'method': 'method text'}, 'rank_by': 'method', 'k': 3})
    assert out['query']['rank_by'] == 'method'
    assert [r['rank'] for r in out['results']] == [1, 2, 3]
