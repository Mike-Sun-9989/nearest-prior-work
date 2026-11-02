import json
import os

import httpx
import pytest

from nearest_prior_work.paragraphs import read_paragraphs
from nearest_prior_work.structure import ModelError, chat, check_config, cut, map_sections, validate

W = "word " * 60


def P(text, kind="P"):
    return {"kind": kind, "text": text}


def test_validate_matches_index_build_checks():
    js = {"paper_type": "quantitative_empirical", "sections": [{"start": 0, "label": "front_matter"}, {"start": 3, "label": "x"}]}
    assert validate(js, 5) == (True, [])
    assert "start out of range" in validate({**js, "sections": [{"start": 0, "label": "a"}, {"start": 9, "label": "b"}]}, 5)[1]
    assert "first section does not start at 0" in validate({**js, "sections": [{"start": 1, "label": "a"}]}, 5)[1]
    assert "bad paper_type" in validate({**js, "paper_type": "novel"}, 5)[1]


def test_map_sections_follows_index_rules():
    pars = [P("A Title", "H"), P("Abstract. We study firms. " + W), P("Introduction", "H"), P(W),
            P("Theory", "H"), P(W), P("Hypothesis tests", "H"), P(W), P("Data", "H"), P(W),
            P("Results", "H"), P(W), P("Hypothesis Tests", "H"), P(W), P("References", "H"), P("A. 2001.")]
    js = {"paper_type": "quantitative_empirical", "title_par": 0, "sections": [
        {"start": 0, "heading": None, "label": "front_matter", "level": 1},
        {"start": 1, "heading": None, "label": "abstract", "level": 1},
        {"start": 2, "heading": "Introduction", "label": "introduction", "level": 1},
        {"start": 4, "heading": "Theory", "label": "theory", "level": 1},
        {"start": 6, "heading": "Hypothesis tests", "label": "hypotheses", "level": 2},
        {"start": 8, "heading": "Data", "label": "data", "level": 1},
        {"start": 10, "heading": "Results", "label": "results", "level": 1},
        {"start": 12, "heading": "Hypothesis Tests", "label": "hypotheses", "level": 2},  # under results: stays results
        {"start": 14, "heading": "References", "label": "references", "level": 1}]}
    rows = map_sections(js["paper_type"], cut(pars, js), title="A Title")
    got = [(r["label"], r["section"]) for r in rows]
    assert got == [("front_matter", None), ("abstract", "abstract"), ("introduction", "introduction"), ("theory", "theory"),
                   ("hypotheses", "theory"), ("data", "method"), ("results", "results"), ("hypotheses", "results"),
                   ("references", None)]
    assert rows[1]["text"].startswith("A Title. We study firms.")
    assert rows[3]["text"].startswith("### Theory\n\n") and "Theory\n\n### Theory" not in rows[3]["text"]


def test_untitled_introduction_after_abstract_and_conceptual_papers():
    long_abs = [P("Abstract", "H"), P("We theorize about status. " + "x " * 130), P("Firms compete for standing. " + W)]
    js = {"paper_type": "conceptual_theory", "sections": [
        {"start": 0, "heading": "Abstract", "label": "abstract", "level": 1},
        {"start": 3, "heading": "Model", "label": "methods", "level": 1}]}
    rows = map_sections(js["paper_type"], cut(long_abs + [P("Model", "H"), P(W)], js))
    secs = [r["section"] for r in rows]
    assert secs == ["abstract", "introduction", "theory"]  # a conceptual paper has no method section


def test_anthropic_and_openai_requests():
    seen = []

    def handler(request):
        seen.append(request)
        if "anthropic" in str(request.url):
            return httpx.Response(200, json={"content": [{"type": "text", "text": "OK"}], "usage": {"input_tokens": 3, "output_tokens": 1}})
        return httpx.Response(401, json={"error": {"message": "Incorrect API key provided"}})
    t = httpx.MockTransport(handler)
    text, usage = chat({"provider": "anthropic", "model": "m", "api_key": "k"}, "sys", "hi", transport=t)
    assert text == "OK" and usage == {"input_tokens": 3, "output_tokens": 1}
    assert seen[-1].headers["x-api-key"] == "k" and json.loads(seen[-1].content)["system"] == "sys"
    with pytest.raises(ModelError, match="401: Incorrect API key"):
        chat({"provider": "deepseek", "model": "m", "api_key": "k"}, "sys", "hi", transport=t)
    assert str(seen[-1].url) == "https://api.deepseek.com/chat/completions"


@pytest.mark.parametrize("cfg,msg", [({"provider": "nope", "model": "m", "api_key": "k"}, "unknown provider"),
                                     ({"provider": "openai", "model": "", "api_key": "k"}, "model name"),
                                     ({"provider": "openai", "model": "m"}, "API key"),
                                     ({"provider": "custom", "model": "m", "api_key": "k"}, "base URL")])
def test_check_config(cfg, msg):
    with pytest.raises(ModelError, match=msg):
        check_config(cfg)
    assert check_config({"provider": "ollama", "model": "qwen3:8b"})["base_url"] == "http://localhost:11434/v1"


def test_paragraphs_for_each_format(tmp_path):
    md = tmp_path / "a.md"
    md.write_text("# Title\n\nFirst para\nstill first.\n\n## Method\n\nTable 1. Sample\n\nSecond.", encoding="utf-8")
    assert [(p["kind"], p["text"]) for p in read_paragraphs(str(md))] == [
        ("H", "Title"), ("P", "First para still first."), ("H", "Method"), ("CAP", "Table 1. Sample"), ("P", "Second.")]
    txt = tmp_path / "a.txt"
    txt.write_text("INTRODUCTION\nWe study firms.\nTheir status matters.", encoding="utf-8")
    assert [p["kind"] for p in read_paragraphs(str(txt))] == ["H", "P", "P"]
    docx_path = os.path.join(os.path.dirname(__file__), "..", "examples", "demo_manuscript.docx")
    pars = read_paragraphs(docx_path)
    heads = [p["text"] for p in pars if p["kind"] == "H"]
    assert heads[:3] == ["Borrowed Standing: How Corporate Investors Shape the Status of the Startups They Fund",
                         "Introduction", "Endorsements, Motives, and the Transfer of Standing"]
    empty = tmp_path / "e.md"
    empty.write_text("\n\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no text"):
        read_paragraphs(str(empty))


def test_cli_agents_run_without_tools_or_api_keys(monkeypatch):
    from nearest_prior_work import structure
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-be-used")
    monkeypatch.setattr(structure, "cli_path", lambda prov: f"/bin/{prov}")
    seen = {}

    def codex(cmd, stdin, cwd):
        seen["codex"] = (cmd, stdin, cwd, structure._cli_env())
        ev = [{"type": "thread.started"}, {"type": "item.completed", "item": {"type": "agent_message", "text": "OK"}},
              {"type": "turn.completed", "usage": {"input_tokens": 12, "output_tokens": 2}}]
        return 0, "\n".join(json.dumps(e) for e in ev), ""
    text, usage = structure.chat({"provider": "codex-cli", "model": "gpt-6.1-sol"}, "SYS", "hello", transport=codex)
    cmd, stdin, cwd, env = seen["codex"]
    assert text == "OK" and usage == {"input_tokens": 12, "output_tokens": 2} and stdin == "hello"
    assert cmd[:2] == ["/bin/codex-cli", "exec"] and cmd[-1] == "-" and "--ignore-user-config" in cmd and "--ephemeral" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only" and "features.shell_tool=false" in cmd
    assert "model_reasoning_effort=\"low\"" in cmd and cmd[cmd.index("-m") + 1] == "gpt-6.1-sol"
    assert "OPENAI_API_KEY" not in env and os.path.basename(cwd) == "work"

    def claude(cmd, stdin, cwd):
        seen["claude"] = cmd
        return 0, json.dumps({"type": "result", "is_error": False, "result": "OK",
                              "usage": {"input_tokens": 5, "cache_read_input_tokens": 7, "output_tokens": 1}}), ""
    text, usage = structure.chat({"provider": "claude-cli"}, "SYS", "hello", transport=claude)
    cmd = seen["claude"]
    assert text == "OK" and usage == {"input_tokens": 12, "output_tokens": 1}
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert "--model" not in cmd  # empty model = the CLI's default

    def failing(cmd, stdin, cwd):
        return 1, json.dumps({"type": "turn.failed", "error": {"message": "You've hit your usage limit"}}), ""
    with pytest.raises(ModelError, match="usage limit"):
        structure.chat({"provider": "codex-cli"}, "SYS", "hello", transport=failing)
    with pytest.raises(ModelError, match="unexpected characters"):
        check_config({"provider": "codex-cli", "model": "x; rm -rf /"})
