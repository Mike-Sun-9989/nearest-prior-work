"""
The section-level index held by the server.

The server loads only article metadata and paper-level section vectors (see docs/server_db_format.md).
Responses are built from an explicit whitelist of fields (`PUBLIC_FIELDS`): article metadata (DOI, title, journal, year),
section names and rounded similarity scores. No abstracts are returned, even when the database file has an abstract
column. Section text and vectors never leave this module, and submitted text is encoded, compared and discarded without
being stored.
"""
import json
import os
import re
import threading
import warnings
import hashlib
import time
from collections import OrderedDict

import numpy as np
import pandas as pd

from ..sections import SECTIONS, canon

MAX_K = 50
MAX_CHARS_PER_SECTION = 150_000
MAX_CHARS_TOTAL = 400_000
CHUNK_TOKENS, CHUNK_OVERLAP, MAX_CHUNKS = 2048, 256, 20  # same chunking as the index build
PUBLIC_FIELDS = {"rank", "doi", "title", "journal", "year", "url", "best_matching_section", "similarity"}
HOW_TO_READ = ("by_section: rank = this article's position among all `of` indexed articles that have that section, "
               "ordered by similarity to your text (rank 1 = closest). percentile: share of 200,000 random pairs of "
               "indexed articles that are less similar in that section (99.9 = more similar than 99.9% of random pairs). "
               "z: standard deviations above the mean random pair. overall_z: mean z over the sections both texts have "
               "(the ranking for manuscripts). best_matching_section: the section where this article stands out most "
               "among all indexed articles. match_score (passage without a section): how many SDs that section stands "
               "out; passages are matched more accurately when the section is given.")


class BGEM3Encoder:
    """BAAI/bge-m3 dense encoder with the chunking used to build the index (2,048 tokens, 256 overlap, mean of chunks)."""

    def __init__(self, model="BAAI/bge-m3", device=None):
        self.model_name, self.device = model, device
        self.model = None
        self.lock = threading.RLock()
        self.status = "not_loaded"

    def _load(self):
        if self.model is not None:
            return
        import torch
        from sentence_transformers import SentenceTransformer
        from ..local import model_dir
        self.status = "preparing"
        device = self.device or ("cuda" if torch.cuda.is_available() else
                                 "mps" if torch.backends.mps.is_available() else "cpu")
        try:
            path = model_dir(self.model_name, log=lambda *_: None)
            try:
                self._open_model(path, device)
            except (RuntimeError, NotImplementedError):
                if device == 'cpu':
                    raise
                fallback = True
            else:
                fallback = False
            if fallback:
                self._release_model()
                self._open_model(path, 'cpu')
        except Exception:
            self.status = "not_loaded"
            raise
        self.status = "ready"

    def _open_model(self, path, device):
        import torch
        from sentence_transformers import SentenceTransformer
        if device == 'cpu':
            torch.set_num_threads(min(8, os.cpu_count() or 1))
        self.device = device
        self.model = SentenceTransformer(path, device=device)
        self.model.max_seq_length = CHUNK_TOKENS
        if device == 'cuda':
            self.model.half()

    def _release_model(self):
        import gc
        import torch
        self.model = None
        gc.collect()
        try:
            if self.device == 'cuda': torch.cuda.empty_cache()
            elif self.device == 'mps': torch.mps.empty_cache()
        except (RuntimeError, AttributeError):
            pass

    def encode(self, text):
        with self.lock:
            try:
                self._load()
                try:
                    return self._encode(text)
                except (RuntimeError, NotImplementedError):
                    if self.device == 'cpu':
                        raise
                # Exit the handler before releasing tensors retained by the traceback.
                self._release_model()
                self.device = 'cpu'
                self._load()
                return self._encode(text)
            except (RuntimeError, MemoryError) as error:
                if isinstance(error, MemoryError) or any(part in str(error).lower() for part in
                        ('out of memory', "can't allocate memory", 'cannot allocate memory', 'not enough memory')):
                    raise QueryError('This search needs more free memory. Close other apps or try a shorter section, then retry. Your input is kept.') from None
                raise

    def _encode(self, text):
        """Return (unit vector, number of tokens, truncated?)."""
        tok = self.model.tokenizer
        ids = tok(text, add_special_tokens=False, verbose=False)["input_ids"]  # we chunk ourselves; no length warning
        step = CHUNK_TOKENS - CHUNK_OVERLAP
        pieces = [tok.decode(ids[st:st + CHUNK_TOKENS - 2]) for st in range(0, max(1, len(ids)), step)
                  if ids[st:st + CHUNK_TOKENS - 2]]
        truncated = len(pieces) > MAX_CHUNKS
        pieces = pieces[:MAX_CHUNKS] or [text]
        with self.lock:
            E = self.model.encode(pieces, batch_size=1, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
        v = E.astype(np.float32).mean(0)
        norm = np.linalg.norm(v)
        if not np.isfinite(v).all() or not np.isfinite(norm) or norm == 0:
            raise RuntimeError('The local search engine returned an invalid encoding.')
        return v / norm, len(ids), truncated


class QueryError(ValueError):
    """A problem with the request that the caller can fix."""


class DOINotIndexed(QueryError):
    """The DOI is valid input but the article is outside the bundled collection."""


def _norm_doi(d):
    d = str(d or "").strip().lower()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", d)


class Index:
    def __init__(self, db_dir, encoder, z_decimals=1, pct_decimals=2):
        self.encoder = encoder
        self._cache = OrderedDict()
        self._cache_lock = threading.Lock()
        self.zd, self.pd_ = z_decimals, pct_decimals
        self.manifest = json.load(open(os.path.join(db_dir, "manifest.json"), encoding="utf-8"))
        self.sections = [s for s in self.manifest["sections"] if s in SECTIONS]
        a = pd.read_parquet(os.path.join(db_dir, "articles.parquet"))
        assert (a.row.to_numpy() == np.arange(len(a))).all()
        self.n = len(a)
        # pandas 3 string columns use NaN; the public JSON contract uses null.
        self.doi = [None if pd.isna(d) else d for d in a.doi.tolist()]
        self.title = a.title.tolist()
        self.journal = a.journal.tolist()
        self.jcode = a.journal_code.str.lower().to_numpy()
        self.jname = a.journal.str.lower().to_numpy()
        self.year = a.year.astype("float").to_numpy()
        self.doi2row = {_norm_doi(d): i for i, d in enumerate(self.doi) if isinstance(d, str)}
        # Counts include articles with missing year metadata; the year range cannot.
        covered = a.assign(year=self.year).groupby("journal").year.agg(["size", "min", "max"])
        self.coverage = [{"journal": j, "articles": int(r["size"]), "year_min": int(r["min"]), "year_max": int(r["max"])}
                         for j, r in covered.iterrows()]
        self.V, self.has = {}, {}
        for s in self.sections:
            P = np.load(os.path.join(db_dir, f"vectors_{s}.npy")).astype(np.float32)
            self.has[s] = ~np.isnan(P).any(1)
            self.V[s] = np.nan_to_num(P)
        rp = np.load(os.path.join(db_dir, "random_pairs.npz"))
        self.rp = {s: np.sort(rp[s]) for s in self.sections}
        self.mu = {s: float(self.rp[s].mean()) for s in self.sections}
        self.sd = {s: float(self.rp[s].std()) for s in self.sections}

    # ---------------------------------------------------------------- public API
    def info(self):
        m = self.manifest
        return {"articles": self.n, "sections": self.sections, "journals": m.get("journals"), "years": m.get("years"),
                "coverage": self.coverage,
                "articles_with_section": m.get("articles_with_section"), "index": m.get("name"),
                "engine_status": getattr(self.encoder, "status", "ready")}

    def _encode(self, text):
        # Bounded, transient cache: hashes and vectors only; no source text on disk.
        key = hashlib.sha256(text.encode("utf-8")).digest()
        with self._cache_lock:
            now = time.monotonic()
            for old in list(self._cache):
                if now - self._cache[old][0] > 900:
                    del self._cache[old]
            if key in self._cache:
                _, value = self._cache.pop(key)
            else:
                value = self.encoder.encode(text)
            self._cache[key] = (now, value)
            while len(self._cache) > 32:
                self._cache.popitem(last=False)
            return value

    def similar(self, text=None, section=None, sections_text=None, doi=None, k=10, journals=None, year_min=None,
                year_max=None, rank_by=None):
        """
        One of three inputs:
          text (+ optional section): a passage or one section. With a section, articles are ranked by that section; without
              one, the passage is compared with every section and each article is scored by its best-matching section.
          sections_text: {section: text} for several sections of a manuscript; ranked by mean z over shared sections.
          doi: an article already in the index; ranked by mean z over shared sections.
        """
        k = max(1, min(int(k or 10), MAX_K))
        notes, words = [], {}
        given = [x for x in (text, sections_text, doi) if x]
        if len(given) != 1:
            raise QueryError("give exactly one of text, sections_text or doi")
        src = None
        if doi:
            src = self.doi2row.get(_norm_doi(doi))
            if src is None:
                raise DOINotIndexed(f"DOI not in the index: {doi}")
            qv = {s: self.V[s][src] for s in self.sections if self.has[s][src]}
            mode = "article"
        else:
            if text:
                if not isinstance(text, str):
                    raise QueryError("text must be a string")
                if section:
                    s = canon(section)
                    if s not in self.sections:
                        raise QueryError(f"unknown section {section!r}; use one of {self.sections}")
                    sections_text, mode = {s: text}, "section"
                else:
                    sections_text, mode = {"*": text}, "passage"
            else:
                if not isinstance(sections_text, dict):
                    raise QueryError("sections_text must be an object such as {\"theory\": \"...\", \"method\": \"...\"}")
                clean = {}
                for key, val in sections_text.items():
                    s = canon(key)
                    if s not in self.sections:
                        raise QueryError(f"unknown section {key!r}; use one of {self.sections}")
                    if isinstance(val, str) and val.strip():
                        clean[s] = clean.get(s, "") + ("\n\n" if s in clean else "") + val
                if not clean:
                    raise QueryError("sections_text has no non-empty section")
                sections_text = clean
                mode = "manuscript" if len(clean) > 1 else "section"
            total = sum(len(v) for v in sections_text.values())
            if total > MAX_CHARS_TOTAL or any(len(v) > MAX_CHARS_PER_SECTION for v in sections_text.values()):
                raise QueryError(f"text too long (max {MAX_CHARS_PER_SECTION:,} characters per section, "
                                 f"{MAX_CHARS_TOTAL:,} in total)")
            qv = {}
            for s, t in sections_text.items():
                v, ntok, trunc = self._encode(t)
                words[s] = len(t.split())
                if trunc:
                    notes.append(f"{s}: only the first ~{MAX_CHUNKS * (CHUNK_TOKENS - CHUNK_OVERLAP):,} tokens were used")
                if words[s] < 40:
                    notes.append(f"{s}: very short text ({words[s]} words); similarity is less reliable")
                if words[s] < 500:
                    notes.append(f"{'passage' if s == '*' else s}: short text ({words[s]} words). Percentile and z "
                                 "compare with pairs of full sections, so they run low for a passage; judge the match "
                                 "by rank (position among all indexed articles) instead")
                qv[s] = v
        if not qv:
            raise QueryError("that article has no indexed sections")
        ranking = canon(rank_by) if rank_by else None
        if rank_by and mode == "article" and ranking in self.sections and ranking not in qv:
            raise QueryError(f"This article has no indexed {ranking.capitalize()} section. Choose another section.")
        if rank_by and (ranking is None or ranking not in qv or mode == "passage"):
            raise QueryError("choose a ranking section present in the query")

        ok = self._filter(journals, year_min, year_max)
        if src is not None:
            ok[src] = False
        # z: cosine standardized by random article pairs in that section (the evaluated "overall" ranking uses its mean).
        # qz: cosine standardized across all indexed articles for this query. Random-pair z favours short sections
        # (abstracts), so the best-matching section and the passage ranking use qz and the article's rank in each section.
        # On 160 held-out 150-word passages this raised the correct best section from 19% to 59%.
        qsrc = {s: qv["*"] for s in self.sections} if mode == "passage" else qv
        z, qz, srank = {}, {}, {}
        for s, v in qsrc.items():
            c = np.where(self.has[s], self.V[s] @ v, np.nan)
            z[s] = (c - self.mu[s]) / self.sd[s]
            qz[s] = (c - np.nanmean(c)) / np.nanstd(c)
            order_s = np.argsort(-np.nan_to_num(c, nan=-np.inf))
            srank[s] = np.empty(self.n, dtype=np.int64)
            srank[s][order_s] = np.arange(1, self.n + 1)
            if src is not None and self.has[s][src]:  # do not count the source article itself
                srank[s][srank[s] > srank[s][src]] -= 1
        Z = np.vstack([(qz if mode == "passage" else z)[s] for s in qsrc])
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # articles without any compared section
            score = np.nanmax(Z, 0) if mode == "passage" else np.nanmean(Z, 0)
        overall = score.copy()
        if ranking:
            score = z[ranking].copy()
        score[~ok | np.isnan(score)] = -np.inf
        top = [i for i in np.argsort(-score)[:k] if np.isfinite(score[i])]
        names = list(qsrc)
        nsec = {s: int(self.has[s].sum()) - int(src is not None and self.has[s][src]) for s in names}
        results = []
        for r, i in enumerate(top, 1):
            per = {s: float(z[s][i]) for s in names if np.isfinite(z[s][i])}
            order = sorted(per, key=lambda s: -float(qz[s][i]))
            shown = order[:3] if mode == "passage" else order
            by_sec = {s: {"rank": int(srank[s][i]), "of": nsec[s], "percentile": self._pct(s, per[s]),
                          "z": round(per[s], self.zd)} for s in shown}
            sim = {"by_section": by_sec}
            if mode == "passage":
                sim = {"match_score": round(float(score[i]), self.zd), **sim}
            elif len(names) > 1:
                sim = {"overall_z": round(float(overall[i]), self.zd), "sections_shared": len(per), **sim}
            results.append(self._card(i, rank=r, best_matching_section=order[0], similarity=sim))
        query = {"mode": mode, "sections_compared": self.sections if mode == "passage" else names,
                 "rank_by": ranking or "overall", "rank_scope": "all indexed articles with this section; source excluded",
                 "filters": {"journals": journals, "year_min": year_min, "year_max": year_max},
                 "index": self.manifest.get("name"), "eligible_articles": int(np.isfinite(score).sum())}
        if words:
            query["words"] = {("passage" if s == "*" else s): w for s, w in words.items()}
        if src is not None:
            query["source"] = self._card(src)
        out = {"query": query, "n_results": len(results), "results": results, "how_to_read": HOW_TO_READ}
        if notes:
            out["notes"] = notes
        return out

    def article(self, doi):
        i = self.doi2row.get(_norm_doi(doi))
        if i is None:
            raise QueryError(f"DOI not in the index: {doi}")
        card = self._card(i)
        card["indexed_sections"] = [s for s in self.sections if self.has[s][i]]
        return card

    # ---------------------------------------------------------------- internals
    def _pct(self, s, z):
        c = z * self.sd[s] + self.mu[s]
        p = 100.0 * np.searchsorted(self.rp[s], c) / len(self.rp[s])
        return round(min(float(p), 99.99), self.pd_)

    def _filter(self, journals, year_min, year_max):
        ok = np.ones(self.n, dtype=bool)
        if journals:
            if isinstance(journals, str):
                journals = [journals]
            js = {str(j).strip().lower() for j in journals}
            ok &= np.isin(self.jcode, list(js)) | np.isin(self.jname, list(js))
        with np.errstate(invalid="ignore"):
            if year_min:
                ok &= self.year >= int(year_min)
            if year_max:
                ok &= self.year <= int(year_max)
        return ok

    def _card(self, i, **extra):
        d = self.doi[i]
        y = self.year[i]
        card = {"doi": d, "title": self.title[i], "journal": self.journal[i], "year": int(y) if np.isfinite(y) else None,
                "url": f"https://doi.org/{d}" if d else None}
        card = {**{k: v for k, v in extra.items() if k == "rank"}, **card, **{k: v for k, v in extra.items() if k != "rank"}}
        assert set(card) <= PUBLIC_FIELDS, set(card) - PUBLIC_FIELDS
        return card
