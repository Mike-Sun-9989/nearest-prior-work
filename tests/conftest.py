"""A tiny synthetic index (random vectors, made-up articles) so tests run without the private database or BGE-M3."""
import hashlib
import json
import os

import numpy as np
import pandas as pd
import pytest

N, DIM = 40, 32
SECS = ["abstract", "introduction", "theory", "method", "discussion"]


def unit(v):
    return (v / np.linalg.norm(v)).astype(np.float32)


class FakeEncoder:
    """Deterministic text -> vector. Texts registered with `pin` map to a given vector."""

    def __init__(self):
        self.pinned = {}

    def pin(self, text, vec):
        self.pinned[text] = vec

    def encode(self, text):
        if text in self.pinned:
            return self.pinned[text], len(text.split()), False
        seed = int(hashlib.md5(text.encode()).hexdigest()[:8], 16)
        return unit(np.random.default_rng(seed).normal(size=DIM)), len(text.split()), False


def make_db(d, offline=False):
    """Synthetic database. offline=True mimics the offline data package (metadata only); the server database keeps an
    abstract column, which the index must never return."""
    os.makedirs(d, exist_ok=True)
    rng = np.random.default_rng(0)
    arts = pd.DataFrame({
        "row": np.arange(N, dtype="int32"),
        "doi": [f"10.9999/test.{i}" if i != 5 else None for i in range(N)],
        "title": [f"Test article {i}" for i in range(N)],
        "journal": ["Strategic Management Journal" if i % 2 else "Organization Science" for i in range(N)],
        "journal_code": ["smj" if i % 2 else "os" for i in range(N)],
        "year": pd.array([1996 + i % 30 for i in range(N)], dtype="Int16"),
    })
    if not offline:
        arts["abstract"] = [f"Public abstract {i}." for i in range(N)]
    arts.to_parquet(os.path.join(d, "articles.parquet"), index=False)
    rp = {}
    for s in SECS:
        P = np.vstack([unit(rng.normal(size=DIM)) for _ in range(N)])
        if s == "method":
            P[:10] = np.nan  # conceptual articles have no method section
        np.save(os.path.join(d, f"vectors_{s}.npy"), P.astype(np.float16))
        rp[s] = np.sort(rng.normal(0.0, 0.18, 5000)).astype(np.float32)
    np.savez(os.path.join(d, "random_pairs.npz"), **rp)
    files = {f: hashlib.sha256(open(os.path.join(d, f), "rb").read()).hexdigest() for f in sorted(os.listdir(d))}
    json.dump({"name": "test_db", "sections": SECS, "n_articles": N, "journals": ["Organization Science",
               "Strategic Management Journal"], "years": [1996, 2025], "files": files},
              open(os.path.join(d, "manifest.json"), "w"))
    return str(d)


@pytest.fixture(scope="session")
def db_dir(tmp_path_factory):
    return make_db(tmp_path_factory.mktemp("db"))


@pytest.fixture(scope="session")
def offline_db_dir(tmp_path_factory):
    return make_db(tmp_path_factory.mktemp("offline") / "npw_test_package", offline=True)


@pytest.fixture()
def index(db_dir):
    from nearest_prior_work.server.index import Index
    return Index(db_dir, FakeEncoder())


def walk(x, path=""):
    """Yield (path, value) for every leaf of a JSON-like object."""
    if isinstance(x, dict):
        for k, v in x.items():
            yield from walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        yield path, x
        for i, v in enumerate(x):
            yield from walk(v, f"{path}[{i}]")
    else:
        yield path, x


def assert_no_vectors_or_text(out, submitted=()):
    """No list of numbers (a vector), and none of the submitted text echoed back."""
    for path, v in walk(out):
        if isinstance(v, list):
            assert not (len(v) > 3 and all(isinstance(e, (int, float)) for e in v)), f"numeric list at {path}"
        if isinstance(v, str):
            for t in submitted:
                assert t not in v, f"submitted text echoed at {path}"
