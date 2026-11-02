"""
Find a manuscript's sections with the user's own language model, the way the index itself was built.

The index was built in three steps: a language model read each article as numbered paragraphs and returned only its
structure (paper type, and where each section starts, with a label and level); code cut the original paragraphs at those
starts; fixed rules mapped the labels to the index sections (introduction, theory, method, ...). This module repeats
the same steps for a manuscript, with the same prompt, labels and rules, so a manuscript's "theory" means what the
index's "theory" means. The model never rewrites text: every section is the manuscript's own paragraphs.

Models: the command-line agent the user already has and is signed in to, so their subscription pays (Codex CLI with a
ChatGPT plan, Claude Code with a Claude plan); or, for those who prefer, any OpenAI-compatible chat API or Anthropic's
API with a key.

The command-line agents run as a plain model: no tools, no shell, a read-only sandbox in an empty temporary folder, no
user configuration, memory, project instructions or saved session, and API-key variables removed from their
environment so they use the signed-in plan. The manuscript reaches the model as data in the prompt.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time

import httpx

from .paragraphs import read_paragraphs

CLIS = {  # provider -> (label, command names to look for, fallback install paths)
    "codex-cli": ("Codex CLI", ["codex.cmd", "codex"], [os.path.join(os.environ.get("APPDATA", ""), "npm", "codex.cmd")]),
    "claude-cli": ("Claude Code", ["claude"], [os.path.join(os.path.expanduser("~"), ".local", "bin", "claude.exe"),
                                              os.path.join(os.path.expanduser("~"), ".local", "bin", "claude")]),
}
CLI_TIMEOUT = 540
CLI_EFFORT = "low"  # finding section starts is a reading task; the index build used low effort too
API_KEY_VARS = ("OPENAI_API_KEY", "CODEX_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
CODEX_OFF = ["shell_tool", "shell_snapshot", "unified_exec", "unified_exec_tty", "code_mode_host", "code_mode_interrupt",
             "multi_agent", "image_generation", "apps", "plugins", "browser_use", "computer_use", "in_app_browser",
             "view_image", "memories", "hooks"]
PROVIDERS = {  # name -> (api style, default base URL)
    "openai": ("openai", "https://api.openai.com/v1"),
    "anthropic": ("anthropic", "https://api.anthropic.com"),
    "deepseek": ("openai", "https://api.deepseek.com"),
    "qwen": ("openai", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
    "qwen-intl": ("openai", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
    "glm": ("openai", "https://open.bigmodel.cn/api/paas/v4"),
    "kimi": ("openai", "https://api.moonshot.ai/v1"),
    "ollama": ("openai", "http://localhost:11434/v1"),
    "custom": ("openai", None),
}
TIMEOUT = 300
PROMPT_VERSION = "v2"  # v2 (2026-10-30): abstract may be small print (FN) or placed after the introduction starts
MAX_PROMPT_CHARS = 200_000  # beyond this, long paragraphs are shortened in the prompt only (structure needs their starts)


class ModelError(RuntimeError):
    """The model could not be reached or did not return a usable structure."""


# ------------------------------------------------------------------ command-line agents (subscription)
def cli_path(provider):
    _, names, fallbacks = CLIS[provider]
    for n in names:
        p = shutil.which(n)
        if p:
            return p
    return next((p for p in fallbacks if os.path.isfile(p)), None)


def find_clis():
    """Which command-line agents are installed: {provider: {"label", "found", "version"}}."""
    out = {}
    for prov, (label, _, _) in CLIS.items():
        p, ver = cli_path(prov), None
        if p:
            try:
                r = subprocess.run([p, "--version"], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   timeout=30, env=_cli_env())
                ver = (r.stdout or r.stderr).strip().splitlines()[0][:60] if (r.stdout or r.stderr).strip() else None
            except (OSError, subprocess.SubprocessError):
                p = None
        compatible, signed_in = False, None
        if p:
            try:
                help_args = ['exec', '--help'] if prov == 'codex-cli' else ['--help']
                h = subprocess.run([p, *help_args], capture_output=True, text=True, timeout=10, env=_cli_env())
                required = ('--ephemeral', '--ignore-user-config') if prov == 'codex-cli' else ('--strict-mcp-config', '--effort')
                compatible = h.returncode == 0 and all(flag in h.stdout for flag in required)
                login_args = ['login', 'status'] if prov == 'codex-cli' else ['auth', 'status', '--json']
                login = subprocess.run([p, *login_args], capture_output=True, text=True, timeout=10, env=_cli_env())
                if prov == 'codex-cli':
                    signed_in = login.returncode == 0
                else:
                    signed_in = bool(json.loads(login.stdout).get('loggedIn'))
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        out[prov] = {"label": label, "found": bool(p), "version": ver, 'compatible': compatible, 'signed_in': signed_in}
    return out


def _cli_env():
    env = {k: v for k, v in os.environ.items() if k not in API_KEY_VARS}  # use the signed-in plan, not an API key
    env.update({"NO_COLOR": "1", "CLAUDE_CODE_SKIP_PROMPT_HISTORY": "1"})
    return env


def _run(cmd, stdin, cwd):
    try:
        r = subprocess.run(cmd, input=stdin, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=CLI_TIMEOUT, cwd=cwd, env=_cli_env())
    except subprocess.TimeoutExpired as e:
        raise ModelError('The agent took too long. Check your login and connection, then retry.') from e
    except OSError as e:
        raise ModelError('The agent could not start. Follow Install and sign in in Model settings, then choose Recheck.') from e
    return r.returncode, r.stdout, r.stderr


def cli_failure(label, detail):
    lower = str(detail).lower()
    if any(x in lower for x in ('usage limit', 'quota', 'rate limit', 'allowance')):
        return f'{label} usage limit reached. Check your plan allowance or wait before retrying.'
    if any(x in lower for x in ('login', 'log in', 'sign in', 'unauthorized', 'authentication')):
        return f'{label} needs a valid login. Follow the sign-in steps in Model settings, then Recheck and Test connection.'
    return f'{label} could not complete the request. Check your login, plan allowance and model name; update the agent, then Recheck and Test connection.'


def _cli_chat(c, system, user, runner):
    label = CLIS[c["provider"]][0]
    exe = cli_path(c["provider"])
    if not exe:
        raise ModelError(f"{label} is not installed on this computer (or not on PATH)")
    with tempfile.TemporaryDirectory(prefix="npw_cli_") as tmp:
        sys_file = os.path.join(tmp, "instructions.md")
        with open(sys_file, "w", encoding="utf-8") as f:
            f.write(system)
        work = os.path.join(tmp, "work")
        os.makedirs(work)
        if c["provider"] == "codex-cli":
            cmd = [exe, "exec", "--json", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules",
                   "--sandbox", "read-only", "-C", work,
                   "-c", f"model_reasoning_effort={json.dumps(c['effort'])}", "-c", "approval_policy=\"never\"",
                   "-c", "web_search=\"disabled\"", "-c", "history.persistence=\"none\"", "-c", "project_doc_max_bytes=0",
                   "-c", f"model_instructions_file={json.dumps(sys_file)}"]
            cmd += [x for f in CODEX_OFF for x in ("-c", f"features.{f}=false")]
            if c["model"]:
                cmd += ["-m", c["model"]]
            code, out, err = runner(cmd + ["-"], user, work)
            events = []
            for line in out.splitlines():
                try:
                    events.append(json.loads(line))
                except ValueError:
                    pass
            msgs = [(e.get("item") or {}).get("text") for e in events
                    if e.get("type") == "item.completed" and (e.get("item") or {}).get("type") == "agent_message"]
            fails = [str(e.get("message") or (e.get("error") or {}).get("message") or "") for e in events
                     if e.get("type") in ("error", "turn.failed")]
            u = next((e.get("usage") for e in reversed(events) if e.get("type") == "turn.completed"), None) or {}
            if not msgs:
                why = (fails[-1] if fails else "") or err.strip().splitlines()[-1:] or [f"exit code {code}"]
                raise ModelError(cli_failure(label, why))
            return msgs[-1], {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
        cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--max-turns", "1", "--system-prompt-file", sys_file,
               "--settings", json.dumps({"disableAllHooks": True, "autoMemoryEnabled": False}),
               "--no-session-persistence", "--permission-mode", "dontAsk", "--strict-mcp-config", "--effort", c["effort"]]
        if c["model"]:
            cmd += ["--model", c["model"]]
        code, out, err = runner(cmd, user, work)
        try:
            js = json.loads(out.strip().splitlines()[-1]) if out.strip() else {}
        except ValueError:
            js = {}
        if code != 0 or js.get("is_error") or not js.get("result"):
            why = js.get("result") or (err.strip().splitlines() or [f"exit code {code}"])[-1]
            raise ModelError(cli_failure(label, why))
        u = js.get("usage") or {}
        return js["result"], {"input_tokens": (u.get("input_tokens") or 0) + (u.get("cache_read_input_tokens") or 0)
                              + (u.get("cache_creation_input_tokens") or 0), "output_tokens": u.get("output_tokens")}


# ------------------------------------------------------------------ model access
def check_config(cfg):
    if not isinstance(cfg, dict):
        raise ModelError("model settings missing: connect a model first")
    prov = str(cfg.get("provider") or "").lower()
    if prov in CLIS:
        effort = str(cfg.get("effort") or CLI_EFFORT)
        if not re.fullmatch(r"[a-z]{2,10}", effort):
            raise ModelError("effort must be a word such as low, medium or high")
        model = str(cfg.get("model") or "").strip()
        if model and not re.fullmatch(r"[A-Za-z0-9._:/\[\]-]{1,80}", model):
            raise ModelError("model name has unexpected characters")
        return {"provider": prov, "style": "cli", "model": model, "effort": effort}
    if prov not in PROVIDERS:
        raise ModelError(f"unknown provider {prov!r}; use one of {', '.join(list(CLIS) + list(PROVIDERS))}")
    style, default = PROVIDERS[prov]
    base = (cfg.get("base_url") or default or "").strip().rstrip("/")
    if not re.match(r"^https?://", base):
        raise ModelError("base URL must start with http:// or https://")
    model = str(cfg.get("model") or "").strip()
    if not model:
        raise ModelError("model name missing")
    key = str(cfg.get("api_key") or "").strip()
    if not key and prov != "ollama":
        raise ModelError("API key missing")
    return {"provider": prov, "style": style, "base_url": base, "model": model, "api_key": key}


def chat(cfg, system, user, max_tokens=8000, transport=None):
    """One chat call; returns (text, usage dict). `transport` lets tests replace the HTTP layer (an httpx transport) or
    the command-line run (a function (cmd, stdin, cwd) -> (exit code, stdout, stderr))."""
    c = check_config(cfg)
    if c["style"] == "cli":
        runner = transport if callable(transport) and not isinstance(transport, httpx.BaseTransport) else _run
        return _cli_chat(c, system, user, runner)
    if c["style"] == "anthropic":
        url = c["base_url"] + "/v1/messages"
        headers = {"x-api-key": c["api_key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
        body = {"model": c["model"], "max_tokens": max_tokens, "system": system,
                "messages": [{"role": "user", "content": user}]}
    else:
        url = c["base_url"] + "/chat/completions"
        headers = {"content-type": "application/json"}
        if c["api_key"]:
            headers["authorization"] = "Bearer " + c["api_key"]
        body = {"model": c["model"], "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        body['max_completion_tokens' if c['provider']=='openai' else 'max_tokens'] = max_tokens
    try:
        with httpx.Client(timeout=TIMEOUT, transport=transport) as h:
            r = h.post(url, headers=headers, json=body)
    except httpx.TimeoutException as e:
        raise ModelError('The model timed out. Check your connection or choose another model and retry.') from e
    except httpx.HTTPError as e:
        raise ModelError('Could not reach the model service. Check the API address and your internet connection; for a local model, start its application first.') from e
    check_response(r)
    try:
        js = r.json()
        if c["style"] == "anthropic":
            text = "".join(b.get("text", "") for b in js.get("content", []) if b.get("type") == "text")
            u = js.get("usage") or {}
            usage = {"input_tokens": u.get("input_tokens"), "output_tokens": u.get("output_tokens")}
        else:
            text = js['choices'][0]['message']['content']
            u = js.get("usage") or {}
            usage = {"input_tokens": u.get("prompt_tokens"), "output_tokens": u.get("completion_tokens")}
        if not isinstance(text, str) or not text.strip(): raise ValueError('empty')
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ModelError('The service returned no usable text. Choose a chat-capable model and check the API address, then test again.') from None
    return text, usage


def test_model(cfg, transport=None):
    t0 = time.time()
    text, _ = chat(cfg, "You are a connection test.", "Reply with the single word OK.", max_tokens=200, transport=transport)
    if not isinstance(text, str) or text.strip().strip('"\' .!').upper() != 'OK':
        raise ModelError('The model did not answer the connection test as requested. Choose a chat-capable model and test again.')
    return {"ok": True, "reply": 'OK', "seconds": round(time.time() - t0, 1)}


def check_response(response):
    if response.status_code == 200: return
    advice = {401:'Incorrect API key or expired credentials. Replace the key and test again.',
              403:'This key cannot use the service. Check account permissions and model access.',
              404:'Model or API address not found. Check both fields; use Load available models if supported.',
              429:'The service limit was reached. Check your allowance or billing, wait, then retry.',
              400:'The service rejected this request. Check the model name and API address.'}
    raise ModelError(f"The model API answered {response.status_code}: " + advice.get(response.status_code,
                     'The service is unavailable. Try again later or choose another provider.'))


def list_models(cfg, transport=None):
    c = check_config({**cfg, 'model': cfg.get('model') or '_list_'})
    if c['style'] == 'cli': raise ModelError('Leave Model blank to use your agent default.')
    headers = {'x-api-key': c['api_key'], 'anthropic-version':'2023-06-01'} if c['style'] == 'anthropic' else {}
    if c['api_key'] and c['style'] != 'anthropic': headers['authorization'] = 'Bearer ' + c['api_key']
    url = c['base_url'] + ('/v1/models' if c['style'] == 'anthropic' else '/models')
    try:
        with httpx.Client(timeout=20, transport=transport) as h: response = h.get(url, headers=headers)
        check_response(response)
        data = response.json()['data']
        models = sorted({r['id'] for r in data if isinstance(r.get('id'), str) and len(r['id']) <= 200})
        if not models: raise ValueError('empty')
        return {'models':models[:500]}
    except httpx.HTTPError:
        raise ModelError('Could not load the model list. Check the address and connection, or enter a model name from your provider.') from None
    except (ValueError, KeyError, TypeError, AttributeError):
        raise ModelError('This service does not provide a model list. Enter a chat model name from your provider instead.') from None


# ------------------------------------------------------------------ prompt (the index build's prompt, atlas/16)
TYPES = {
    "quantitative_empirical": "tests or estimates relationships with quantitative data (archival, survey, experiment, econometrics)",
    "qualitative_empirical": "case study, ethnography, interviews, grounded theory, qualitative field data",
    "mixed_methods": "substantial quantitative AND qualitative empirical components",
    "conceptual_theory": "develops theory or propositions without new empirical data",
    "review_meta_analysis": "literature review, systematic review, or meta-analysis",
    "formal_model": "analytical / mathematical / game-theoretic / operations-research model with derivations or proofs",
    "simulation_computational": "agent-based, NK, or other computational simulation as the main method",
    "methodological": "about research methods or measurement themselves",
    "other": "editorial, commentary, reply, essay, introduction to a special issue, or anything else",
}
LABELS = ["front_matter", "abstract", "introduction", "literature_review", "theory", "hypotheses", "propositions", "conceptual_model",
          "research_setting", "data", "methods", "measures", "model", "analysis", "results", "findings", "robustness",
          "additional_analyses", "case_description", "discussion", "implications", "limitations", "future_research", "conclusion",
          "appendix", "references", "acknowledgments", "other"]
SYSTEM = f"""You read the full text of one management research article or manuscript, split into numbered paragraphs.
Each line is "[number] TYPE text", where TYPE is H (detected heading), P (paragraph), CAP (table/figure caption) or FN (footnote or other small print). Heading detection is imperfect: some H lines are author names or broken paragraph starts, and some real headings appear as P. Some journals set the abstract in small print, so it can appear as FN, and on the first page it can come after the first paragraphs of the introduction; label it abstract wherever it is.

Your job:
1. Classify the article into ONE paper type: {json.dumps(TYPES)}
2. Divide the article into consecutive sections. For each section give the paragraph number where it starts, the printed heading text (or null if the section has no printed heading, e.g. an untitled introduction), a label, and a level (1 = main section, 2 = subsection worth separating, such as robustness checks inside results, hypotheses inside theory, or limitations inside discussion).
   Suggested labels (use these when they fit; otherwise write a short lowercase label): {", ".join(LABELS)}.
   The first section starts at paragraph 0 (usually front_matter: title, authors, affiliations, journal info). Cover the whole article; sections run until the next section's start.
   If the abstract and an untitled introduction follow each other, start a separate introduction section where the introduction begins.
3. Give the number of the paragraph that holds the article's title (title_par), or null if there is none.
Do not rewrite or summarize the text. Return ONLY JSON:
{{"paper_type": "...", "title_par": 1, "sections": [{{"start": 0, "heading": null, "label": "front_matter", "level": 1}}, ...], "notes": "anything unusual, <= 20 words"}}"""


def doc_text(pars):
    lines = [f"[{i}] {p['kind']} {p['text']}" for i, p in enumerate(pars)]
    if sum(len(x) for x in lines) > MAX_PROMPT_CHARS:
        lines = [f"[{i}] {p['kind']} {' '.join(p['text'].split()[:60])}{' …' if len(p['text'].split()) > 60 else ''}"
                 for i, p in enumerate(pars)]
    return "\n".join(lines)


def validate(js, n):
    """Starts increasing, in range, first at 0 (the index build's checks); returns (ok, problems)."""
    probs = []
    if not isinstance(js, dict) or js.get("paper_type") not in TYPES:
        probs.append("bad paper_type")
    secs = js.get("sections") if isinstance(js, dict) else None
    if not isinstance(secs, list) or not secs:
        return False, probs + ["no sections"]
    starts = [s.get("start") if isinstance(s, dict) else None for s in secs]
    if not all(isinstance(x, int) and 0 <= x < n for x in starts):
        probs.append("start out of range")
    elif starts != sorted(starts) or len(set(starts)) != len(starts):
        probs.append("starts not strictly increasing")
    if starts and starts[0] != 0:
        probs.append("first section does not start at 0")
    if any(not isinstance(s, dict) or not s.get("label") for s in secs):
        probs.append("missing label")
    return not probs, probs


def ask_structure(cfg, pars, transport=None):
    """The model's structure for the paragraphs; one retry when the structure fails the checks."""
    user, usage = doc_text(pars), {"input_tokens": 0, "output_tokens": 0}
    probs = []
    for attempt in range(2):
        prompt = user if attempt == 0 else (user + "\n\nYour previous answer had these problems: " + "; ".join(probs)
                                            + ". Return corrected JSON only.")
        text, u = chat(cfg, SYSTEM, prompt, transport=transport)
        for k in usage:
            usage[k] += u.get(k) or 0
        m = re.search(r"\{[\s\S]*\}", text or "")
        try:
            js = json.loads(m.group(0)) if m else None
        except ValueError:
            js = None
        ok, probs = validate(js, len(pars))
        if ok:
            return js, usage
        if js and probs == ["starts not strictly increasing"]:
            return js, usage  # repaired when cutting (sorted, de-duplicated), as in the index build
    raise ModelError("the model did not return a usable structure (" + "; ".join(probs or ["no JSON"]) + ")")


# ------------------------------------------------------------------ cut (atlas/17) and map (atlas/18)
MARK = {"H": "### ", "CAP": "[caption] ", "FN": "[footnote] ", "P": ""}
ORDER = ["introduction", "theory", "method", "results", "robustness", "discussion", "conclusion", "body"]
FRAMEWORK = {
    "quantitative_empirical": ["introduction", "theory", "method", "results", "robustness", "discussion", "conclusion"],
    "mixed_methods": ["introduction", "theory", "method", "results", "robustness", "discussion", "conclusion"],
    "qualitative_empirical": ["introduction", "theory", "method", "results", "discussion", "conclusion"],
    "conceptual_theory": ["introduction", "theory", "discussion", "conclusion"],
    "review_meta_analysis": ["introduction", "method", "theory", "results", "discussion", "conclusion"],
    "formal_model": ["introduction", "theory", "method", "results", "robustness", "discussion", "conclusion"],
    "simulation_computational": ["introduction", "theory", "method", "results", "robustness", "discussion", "conclusion"],
    "methodological": ["introduction", "theory", "method", "results", "discussion", "conclusion"],
    "other": ["introduction", "body", "conclusion"],
}
BASE = {"introduction": "introduction", "literature_review": "theory", "theory": "theory", "conceptual_model": "theory",
        "hypotheses": "theory", "propositions": "theory", "background": "theory", "methods": "method", "research_setting": "method",
        "data": "method", "measures": "method", "model": "method", "results": "results", "findings": "results",
        "robustness": "robustness", "additional_analyses": "robustness", "discussion": "discussion", "implications": "discussion",
        "limitations": "discussion", "future_research": "discussion", "summary": "discussion", "conclusion": "conclusion"}
EXCLUDE = {"front_matter", "abstract", "references", "acknowledgments", "appendix"}
NON_BODY_HEAD = re.compile(r"end\s?notes?|^\W*notes?\b|data availability|orcid|supplement|conflict|declaration|funding|badge|biograph|"
                           r"electronic companion|supporting information|resources|author|disclosure|ethic", re.I)
STUDY_HEAD = re.compile(r"\bstudy\s*\d|overview of (the )?(studies|present research|research)|experiment\s*\d", re.I)
RESULT_HEAD = re.compile(r"\bresults?\b|\bfindings?\b", re.I)
METHOD_LABELS = ["methods", "data", "measures", "model", "research_setting"]
_THANKS = re.compile(r"^\W*(we|i) (thank|are grateful|gratefully|acknowledge)|^\W*(the )?authors? (thank|contributed|wrote|"
                     r"is grateful|are grateful)|^\W*all (three|two|four) authors|^\W*this (research|work|paper) was (supported|funded)", re.I)
_ABS_HEAD = re.compile(r"^\W*(abstract|research summary|summary)\W*", re.I)
_NOT_ABSTRACT = re.compile(r"^\W*(managerial (summary|abstract)|key\s?words|jel|©|copyright|received|accepted|revised|"
                           r"published|correspondence|doi\b)", re.I)


def _render(pars, skip_first_heading):
    out = []
    for k, p in enumerate(pars):
        if k == 0 and skip_first_heading and p["kind"] == "H":
            continue
        out.append(MARK.get(p["kind"], "") + p["text"])
    return "\n\n".join(out)


def cut(pars, js):
    """Segments from the structure: each runs from its start to the next start (atlas/17)."""
    n = len(pars)
    secs = sorted({int(s["start"]): s for s in js["sections"]
                   if isinstance(s, dict) and isinstance(s.get("start"), int) and 0 <= s["start"] < n}.values(),
                  key=lambda s: s["start"])
    if not secs or secs[0]["start"] != 0:
        secs = [dict(start=0, heading=None, label="front_matter", level=1)] + secs
    starts = [s["start"] for s in secs] + [n]
    segs, top = [], 0
    for k, s in enumerate(secs):
        lvl = 2 if s.get("level") == 2 and k > 0 else 1
        if lvl == 1:
            top = k
        part = pars[starts[k]:starts[k + 1]]
        text = _render(part, skip_first_heading=bool(s.get("heading")))
        segs.append(dict(seq=k, level=lvl, label=str(s.get("label") or "other"), heading=(s.get("heading") or "").strip(),
                         start=starts[k], end=starts[k + 1], text=text, n_words=len(text.split()), top_seq=top,
                         pars=part))
    return segs


def _canonical(label, start, res_start, ptype, parent):
    lab = (label or "").strip().lower()
    if lab in EXCLUDE:
        return None
    if lab in ("analysis", "case_description"):
        c = "method" if (res_start is None or start < res_start) else "results"
    elif lab == "conceptual_model" and res_start is not None and start >= res_start:
        c = "results"
    else:
        c = BASE.get(lab)
    if c is None:
        return parent
    if ptype == "conceptual_theory" and c in ("method", "results", "robustness"):
        c = "theory"
    elif ptype == "review_meta_analysis" and lab == "findings":
        c = "theory"
    elif ptype == "formal_model":
        if lab in ("analysis", "propositions", "case_description"):
            c = "results"
    elif ptype == "other" and c not in ("introduction", "conclusion"):
        c = "body"
    if c not in FRAMEWORK[ptype]:
        c = {"robustness": "results", "results": "discussion" if ptype == "conceptual_theory" else "results",
             "method": "theory"}.get(c, c)
        if c not in FRAMEWORK[ptype]:
            c = "theory" if "theory" in FRAMEWORK[ptype] else "body"
    return c


def _abstract(seg):
    """The abstract proper inside an abstract segment: its paragraphs without the heading, small print, captions,
    keywords or dates. Returns (abstract text, the paragraphs after it when the abstract segment runs on)."""
    body = [p for p in seg["pars"] if p["kind"] == "P" and not _NOT_ABSTRACT.match(p["text"])]
    if sum(len(p["text"].split()) for p in body) < 40:  # an abstract set in small print (AMR, some OS and MS layouts)
        alt = [p for p in seg["pars"] if p["kind"] in ("P", "FN") and len(p["text"].split()) >= 30
               and not _NOT_ABSTRACT.match(p["text"]) and not _THANKS.match(p["text"])]
        body = alt or body
    taken, words = [], 0
    for p in body:
        if words >= 120:
            break
        taken.append(p)
        words += len(p["text"].split())
    text = " ".join(_ABS_HEAD.sub("", p["text"], count=1) if i == 0 else p["text"] for i, p in enumerate(taken)).strip()
    return text, body[len(taken):]


def map_sections(ptype, segs, title=None):
    """Index section for every segment (atlas/18), plus the abstract as title + ". " + abstract like the index."""
    if ptype not in FRAMEWORK:
        ptype = "other"
    labs = [s["label"].strip().lower() for s in segs]
    rs = [s["start"] for s, lab in zip(segs, labs)
          if (lab in ("results", "findings") and not (ptype == "review_meta_analysis" and lab == "findings"))
          or (lab in ("analysis", "case_description") and s["level"] == 1 and RESULT_HEAD.search(s["heading"] or ""))]
    res_start = min(rs) if rs else None
    if res_start is None:
        meth = [s["start"] for s, lab in zip(segs, labs) if lab in METHOD_LABELS]
        ana = [s["start"] for s, lab in zip(segs, labs)
               if lab in ("analysis", "case_description") and s["start"] > (min(meth) if meth else -1)]
        res_start = min(ana) if ana else None
    needs_intro = sum(s["n_words"] for s, lab in zip(segs, labs) if lab == "introduction") < 100
    canon_of, prev_c, out = {}, None, []
    for s, lab in zip(segs, labs):
        row = {k: v for k, v in s.items() if k != "pars"}
        if lab == "abstract" and s["level"] == 1 and "abstract" not in [r.get("section") for r in out]:
            abs_text, rest = _abstract(s)
            if abs_text:
                row["section"] = "abstract"
                row["text"] = (f"{title}. " if title else "") + abs_text
                row["n_words"] = len(row["text"].split())
                out.append(row)
                rest_text = "\n\n".join(p["text"] for p in rest)
                if needs_intro and len(rest_text.split()) >= 20:
                    out.append(dict(row, seq=row["seq"] + 0.5, heading="(introduction without a heading)",
                                    label="introduction", section="introduction", text=rest_text,
                                    n_words=len(rest_text.split())))
                    prev_c = "introduction"
                canon_of[s["seq"]] = None
                continue
        known = lab in BASE or lab in EXCLUDE or lab in ("analysis", "case_description", "conceptual_model", "other")
        if s["level"] == 2:
            parent = canon_of.get(s["top_seq"])
        elif lab == "other" or not known:
            # a label of the model's own (endnotes, author_biographies, ...) is read like "other": back matter stays out
            h = (s["heading"] or "").lower() + ("" if lab == "other" else " " + lab.replace("_", " "))
            if NON_BODY_HEAD.search(h) or not h.strip():
                parent = None
            elif STUDY_HEAD.search(h):
                parent = "method" if "method" in FRAMEWORK[ptype] else prev_c
            else:
                parent = prev_c if prev_c is not None or ptype != "other" else "body"
        else:
            parent = prev_c
        c = _canonical(s["label"], s["start"], res_start, ptype, parent)
        if s["level"] == 2 and parent is None:
            c = None  # subsections of excluded parts (appendix, references, notes) stay out
        elif (s["level"] == 2 and c is not None and ptype != "other" and parent in ("results", "robustness", "discussion")
              and ORDER.index(c) < ORDER.index(parent) and not (parent == "results" and c == "method")):
            c = parent  # a subsection does not move earlier than its parent section
        if c is not None:
            prev_c = c
        canon_of[s["seq"]] = c
        row["section"] = c
        if c is not None and s["heading"]:
            row["text"] = f"### {s['heading']}\n\n{s['text']}"
            row["n_words"] = len(row["text"].split())
        out.append(row)
    return out


def structure_rows(pars, js):
    """Index section and text for every section of a structure (the model's or an agent's)."""
    tp = js.get("title_par")
    title = pars[tp]["text"] if isinstance(tp, int) and 0 <= tp < len(pars) else None
    return map_sections(js.get("paper_type"), cut(pars, js), title=title), title


# ------------------------------------------------------------------ the agent version (npw-mcp): the agent is the model
AGENT_PAGE_CHARS = 40_000  # one outline page stays well under agents' tool-output limits
AGENT_WORDS = 40           # paragraph openings are enough to place section starts

AGENT_GUIDE = (
    "Mark this manuscript's structure the way the index's articles were marked, then call find_similar_to_manuscript "
    "with file_path and structure. Lines are \"[number] TYPE text\": TYPE is H (detected heading), P (paragraph), CAP "
    "(table/figure caption) or FN (footnote or small print); long paragraphs show only their first words. Heading "
    "detection is imperfect, and some journals set the abstract in small print (FN). "
    f"structure = {{\"paper_type\": one of {list(TYPES)}, \"title_par\": number of the title paragraph or null, "
    "\"sections\": [{\"start\": paragraph number, \"heading\": printed heading or null, \"label\": ..., \"level\": 1 or 2}, "
    "...]}. Sections are consecutive: each runs until the next start; the first starts at 0 (usually front_matter). "
    f"Labels (use these when they fit, otherwise a short lowercase label): {', '.join(LABELS)}. Level 2 = a subsection "
    "worth separating (robustness checks inside results, hypotheses inside theory, limitations inside discussion). If "
    "the abstract and an untitled introduction follow each other, start a separate introduction section where it "
    "begins. Do not rewrite text: the sections compared are cut from the manuscript's own paragraphs.")


def agent_outline(path, start=0):
    """Numbered paragraphs of a manuscript for the user's agent to mark (one page at a time)."""
    pars = read_paragraphs(path)
    start = max(0, int(start or 0))
    lines, size, end = [], 0, start
    for i in range(start, len(pars)):
        p = pars[i]
        w = p["text"].split()
        text = p["text"] if p["kind"] == "H" or len(w) <= AGENT_WORDS else " ".join(w[:AGENT_WORDS]) + f" … ({len(w)} words)"
        line = f"[{i}] {p['kind']} {text}"
        if lines and size + len(line) > AGENT_PAGE_CHARS:
            break
        lines.append(line)
        size += len(line)
        end = i + 1
    out = {"file": os.path.abspath(os.path.expanduser(path)), "paragraphs_total": len(pars),
           "showing": [start, end - 1], "paragraphs": lines, "how_to_mark": AGENT_GUIDE}
    if end < len(pars):
        out["next_start"] = end
        out["note"] = f"more paragraphs follow: call outline_manuscript again with start={end}"
    return out


def sections_from_agent(path, structure):
    """({section: text}, {section: {"from": [...], "words": n}}) from the agent's structure of a manuscript file."""
    pars = read_paragraphs(path)
    if not isinstance(structure, dict):
        raise ValueError("structure must be an object with paper_type, title_par and sections (see outline_manuscript)")
    ok, probs = validate(structure, len(pars))
    if not ok and probs != ["starts not strictly increasing"]:
        raise ValueError("structure problems: " + "; ".join(probs) + f" (the file has {len(pars)} paragraphs, 0 to "
                         f"{len(pars) - 1}; paper_type one of {list(TYPES)})")
    rows, _ = structure_rows(pars, structure)
    texts, used = {}, {}
    for r in rows:
        s = r["section"]
        if not s or not r["text"].strip():
            continue
        texts[s] = (texts.get(s, "") + "\n\n" + r["text"]).strip()
        u = used.setdefault(s, {"from": [], "words": 0})
        u["from"].append(f"[{r['start']}] {r['heading'] or r['label']}")
        u["words"] += r["n_words"]
    if not texts:
        raise ValueError("no section could be compared: check the labels in structure")
    return texts, used


def outline_with_model(path, cfg, transport=None):
    """Outline of a manuscript file made by the model: one row per section the model found, with the index section it
    maps to (or None when it is not compared) and its text, in the format of manuscript.outline(with_text=True)."""
    pars = read_paragraphs(path)
    return outline_from_paragraphs(pars, cfg, transport)


def outline_from_paragraphs(pars, cfg, transport=None):
    """Apply canonical mapping to locally inspected paragraphs."""
    t0 = time.time()
    js, usage = ask_structure(cfg, pars, transport=transport)
    rows, title = structure_rows(pars, js)
    headings = []
    for r in rows:
        plain = re.sub(r"(?m)^(### |\[(footnote|caption)\] )", "", r["text"] or "")
        head = r["heading"] or ("(untitled) " + " ".join(plain.split()[:8]) + " …" if plain.strip() else "(empty)")
        headings.append({"n": len(headings), "heading": head, "level": r["level"], "words": r["n_words"],
                         "label": r["label"], "section": r["section"] or "not used", "text": r["text"]})
    totals = {}
    for h in headings:
        if h["section"] != "not used":
            totals[h["section"]] = totals.get(h["section"], 0) + h["words"]
    c = check_config(cfg)
    who = CLIS[c["provider"]][0] if c["provider"] in CLIS else c["provider"]
    return {"headings": headings, "words_by_section": totals, "paper_type": js.get("paper_type"), "title": title,
            "paragraphs": len(pars), "model": f"{who} / {c['model'] or 'default model'}", "usage": usage,
            "seconds": round(time.time() - t0, 1), "notes": js.get("notes")}
