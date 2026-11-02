"""Local MCP tools for the bundled article index. No index server or application key is needed."""
import argparse
import json
import os
import sys
import traceback

from . import tooldocs
from .client import ServerError
from .structure import agent_outline, sections_from_agent


def build_server(client):
    from mcp.server import MCPServer

    mcp = MCPServer("nearest-prior-work", instructions=tooldocs.INSTRUCTIONS)

    def guarded(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except (ServerError, ValueError, FileNotFoundError) as e:
            return {"error": str(e)}
        except Exception as e:  # noqa: BLE001 (anything else: tell the agent what failed, keep the trace on stderr)
            try:
                traceback.print_exc(file=sys.stderr)
            except Exception:  # noqa: BLE001 (some agents give MCP servers an unusable stderr)
                pass
            return {"error": f"unexpected {type(e).__name__}: {e}"}

    @mcp.tool(name="find_similar_articles", description=tooldocs.FIND_SIMILAR_ARTICLES)
    def find_similar_articles(text: str | None = None, section: str | None = None, doi: str | None = None, k: int = 10,
                              journals: list[str] | None = None, year_min: int | None = None,
                              year_max: int | None = None, rank_by: str | None = None) -> dict:
        return guarded(client.similar, text=text, section=section, doi=doi, k=k, journals=journals, year_min=year_min,
                       year_max=year_max, rank_by=rank_by)

    @mcp.tool(name="find_similar_to_manuscript",
              description=tooldocs.FIND_SIMILAR_TO_MANUSCRIPT + tooldocs.FILE_ARGS)
    def find_similar_to_manuscript(sections_text: dict[str, str] | None = None, file_path: str | None = None,
                                   structure: dict | None = None, k: int = 10,
                                   journals: list[str] | None = None, year_min: int | None = None,
                                   year_max: int | None = None, rank_by: str | None = None) -> dict:
        def run():
            used = None
            texts = sections_text
            if file_path:
                if not structure:
                    raise ValueError("with file_path, also pass structure: call outline_manuscript, mark the sections, "
                                     "then call this tool again")
                texts, used = sections_from_agent(file_path, structure)
            if not texts:
                raise ValueError("give sections_text or file_path")
            out = client.similar(sections_text=texts, k=k, journals=journals, year_min=year_min, year_max=year_max, rank_by=rank_by)
            if used:
                out["query"]["sections_sent"] = used
            return out
        return guarded(run)

    @mcp.tool(name="outline_manuscript", description=tooldocs.OUTLINE_MANUSCRIPT)
    def outline_manuscript(file_path: str, start: int = 0) -> dict:
        return guarded(agent_outline, file_path, start)

    @mcp.tool(name="get_article", description=tooldocs.GET_ARTICLE)
    def get_article(doi: str) -> dict:
        return guarded(client.article, doi)

    return mcp


def check(client):
    print(f"index: {client.server}")
    if getattr(client, "db", None):
        print("  loading the index and the embedding model (the first time can take a few minutes) ...")
    try:
        h = client.health()
        print(f"  reachable: {h['articles']:,} articles, {h['years'][0]}-{h['years'][1]}, sections {', '.join(h['sections'])}")
    except ServerError as e:
        print(f"  NOT reachable: {e}")
        return 1
    try:
        out = client.similar(text="Firms that ally with partners of high status gain legitimacy.", k=1)
        top = out["results"][0]
        print(f"  search works; test query returned: {top['title'][:70]} ({top['journal']}, {top['year']})")
    except ServerError as e:
        print(f"  query failed: {e}")
        return 1
    print("all good. Your agent can now use the nearest-prior-work tools.")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="npw-mcp", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="check the connection and exit")
    ap.add_argument("--outline", metavar="FILE", help="print the outline of a manuscript file and exit (runs locally)")
    ap.add_argument("--local", nargs="?", const="", default=None, metavar="DIR",
                    help="use a custom local index directory (default: bundled index)")
    ap.add_argument("--model", default=None, help="offline mode: BGE-M3 model name or local folder (default BAAI/bge-m3)")
    ap.add_argument("--device", default=None, help="offline mode: cpu or cuda (default: cuda when available)")
    a = ap.parse_args(argv)
    from .local import MODEL, LocalClient
    try:
        client = LocalClient(a.local or None, model=a.model or MODEL, device=a.device)
    except ServerError as e:
        sys.exit(f"error: {e}")
    if a.check:
        sys.exit(check(client))
    if a.outline:
        print(json.dumps(agent_outline(a.outline), indent=1, ensure_ascii=False))
        return
    build_server(client).run("stdio")


if __name__ == "__main__":
    main()
