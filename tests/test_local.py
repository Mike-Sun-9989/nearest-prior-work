"""Offline mode: the index from the data package, searched on this computer (no network)."""
import json
import os
import zipfile

import anyio
import pytest

from conftest import FakeEncoder
from nearest_prior_work.client import ServerError
from nearest_prior_work.local import LocalClient, find_db, install_data
from nearest_prior_work.mcp_client import build_server


def client(db):
    c = LocalClient(db, encoder=FakeEncoder())
    c.index()
    return c


def test_offline_results_have_metadata_only(offline_db_dir):
    c = client(offline_db_dir)
    out = c.similar(text="status and alliances " * 30, section="theory", k=40)
    assert out["n_results"] == 40
    assert all(set(r) <= {"rank", "doi", "title", "journal", "year", "url", "best_matching_section", "similarity"}
               for r in out["results"])
    assert set(c.article("10.9999/test.2")) == {"doi", "title", "journal", "year", "url", "indexed_sections"}


def test_query_errors_become_client_errors(offline_db_dir):
    c = client(offline_db_dir)
    with pytest.raises(ServerError):
        c.similar(text="x", section="funding")
    assert c.health()["mode"] == "local"


def test_mcp_tools_in_offline_mode(offline_db_dir, tmp_path):
    server = build_server(client(offline_db_dir))
    p = tmp_path / "m.md"
    p.write_text("# Introduction\n" + "a b c " * 100 + "\n# Methods\n" + "d e f " * 100 + "\n")
    structure = {"paper_type": "quantitative_empirical", "title_par": None, "sections": [
        {"start": 0, "heading": "Introduction", "label": "introduction", "level": 1},
        {"start": 2, "heading": "Methods", "label": "methods", "level": 1}]}
    res = anyio.run(lambda: server.call_tool("find_similar_to_manuscript",
                                             {"file_path": str(p), "structure": structure, "k": 3}))
    res = res[1] if isinstance(res, tuple) else res
    data = getattr(res, "structured_content", None) or (res if isinstance(res, dict) else json.loads(res.content[0].text))
    assert data["query"]["mode"] == "manuscript" and "abstract" not in data["results"][0]


def zip_package(src, dest, tamper=False):
    name = os.path.basename(src)
    with zipfile.ZipFile(dest, "w") as z:
        for f in sorted(os.listdir(src)):
            data = open(os.path.join(src, f), "rb").read()
            if tamper and f == "vectors_theory.npy":
                data = data[:-4] + b"\0\0\0\1"
            z.writestr(f"{name}/{f}", data)
    return str(dest)


def test_install_data_checks_hashes(offline_db_dir, tmp_path, monkeypatch):
    root = tmp_path / "data"
    dest = install_data(zip_package(offline_db_dir, tmp_path / "pkg.zip"), root=str(root), log=lambda *_: None)
    assert os.path.isfile(os.path.join(dest, "manifest.json"))
    monkeypatch.setattr("nearest_prior_work.local.DATA_ROOT", str(root))
    monkeypatch.setattr("nearest_prior_work.local.BUNDLED_DB", tmp_path / "not-bundled")
    monkeypatch.delenv("NPW_LOCAL_DB", raising=False)
    assert find_db() == dest
    with pytest.raises(ServerError, match="damaged"):
        install_data(zip_package(offline_db_dir, tmp_path / "bad.zip", tamper=True), root=str(root), log=lambda *_: None)
    assert not os.path.exists(dest)  # a damaged package is removed


def test_find_db_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("nearest_prior_work.local.DATA_ROOT", str(tmp_path / "none"))
    monkeypatch.setattr("nearest_prior_work.local.BUNDLED_DB", tmp_path / "not-bundled")
    monkeypatch.delenv("NPW_LOCAL_DB", raising=False)
    with pytest.raises(ServerError, match="bundled article index is missing"):
        find_db()
    with pytest.raises(ServerError, match="manifest"):
        find_db(str(tmp_path))


def test_bundled_index_precedes_legacy_cache(offline_db_dir, tmp_path, monkeypatch):
    from pathlib import Path
    monkeypatch.setattr('nearest_prior_work.local.BUNDLED_DB', Path(offline_db_dir))
    monkeypatch.setattr('nearest_prior_work.local.DATA_ROOT', str(tmp_path / 'empty-cache'))
    monkeypatch.delenv('NPW_LOCAL_DB', raising=False)
    assert find_db() == str(offline_db_dir)
