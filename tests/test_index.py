import numpy as np
import pytest

from conftest import assert_no_vectors_or_text
from nearest_prior_work.server.index import PUBLIC_FIELDS, QueryError

TEXT = "Status signals shape alliance formation among biotechnology firms seeking legitimacy in uncertain markets."


def test_section_query_finds_planted_article(index):
    index.encoder.pin(TEXT, index.V["theory"][17])
    out = index.similar(text=TEXT, section="theory", k=5)
    assert out["query"]["mode"] == "section"
    top = out["results"][0]
    assert top["doi"] == "10.9999/test.17"
    assert top["best_matching_section"] == "theory"
    assert top["similarity"]["by_section"]["theory"]["percentile"] <= 99.99
    assert_no_vectors_or_text(out, [TEXT])


def test_passage_reports_best_section(index):
    index.encoder.pin(TEXT, index.V["method"][23])
    out = index.similar(text=TEXT, k=3)
    assert out["query"]["mode"] == "passage"
    assert out["query"]["sections_compared"] == index.sections
    top = out["results"][0]
    assert top["doi"] == "10.9999/test.23" and top["best_matching_section"] == "method"
    assert len(top["similarity"]["by_section"]) <= 3 and "match_score" in top["similarity"]


def test_manuscript_overall_and_missing_sections(index):
    st = {"theory": "theory text " * 50, "method": "method text " * 50, "abstract": "abstract text " * 50}
    index.encoder.pin(st["theory"], index.V["theory"][3])
    index.encoder.pin(st["method"], index.V["method"][30])
    out = index.similar(sections_text=st, k=50)
    assert out["query"]["mode"] == "manuscript"
    r3 = next(r for r in out["results"] if r["doi"] == "10.9999/test.3")
    assert r3["similarity"]["sections_shared"] == 2  # article 3 has no method vector
    assert "method" not in r3["similarity"]["by_section"]
    assert_no_vectors_or_text(out, list(st.values()))


def test_doi_mode_excludes_source_and_accepts_url_form(index):
    out = index.similar(doi="https://doi.org/10.9999/TEST.12", k=50)
    assert out["query"]["source"]["doi"] == "10.9999/test.12"
    assert all(r["doi"] != "10.9999/test.12" for r in out["results"])


def test_filters_and_k_cap(index):
    out = index.similar(text=TEXT, journals=["smj"], year_min=2000, year_max=2010, k=500)
    assert out["n_results"] <= 50
    assert all(r["journal"] == "Strategic Management Journal" and 2000 <= r["year"] <= 2010 for r in out["results"])
    out = index.similar(text=TEXT, journals="Organization Science", k=50)
    assert {r["journal"] for r in out["results"]} == {"Organization Science"}


def test_only_public_fields(index):
    out = index.similar(text=TEXT, k=50)
    for r in out["results"]:
        assert set(r) <= PUBLIC_FIELDS
    # the test database has an abstract column, as the server database does; it must never be returned
    assert all("abstract" not in r for r in out["results"])
    assert "Public abstract" not in str(out) and "Public abstract" not in str(index.article("10.9999/test.4"))


@pytest.mark.parametrize('missing', [None, np.nan, 'pandas_na'])
def test_article_without_doi_is_returned_with_null_doi(db_dir, monkeypatch, missing):
    import json
    import pandas as pd
    from conftest import FakeEncoder
    from nearest_prior_work.server.index import Index
    original = pd.read_parquet
    def read(*args, **kwargs):
        data = original(*args, **kwargs)
        data['doi'] = data.doi.astype(object)
        data.loc[5, 'doi'] = pd.NA if isinstance(missing, str) else missing
        return data
    monkeypatch.setattr(pd, 'read_parquet', read)
    index = Index(db_dir, FakeEncoder())
    index.encoder.pin(TEXT, index.V["abstract"][5])
    r = index.similar(text=TEXT, section="abstract", k=1)["results"][0]
    assert r["doi"] is None and r["url"] is None and r["title"] == "Test article 5"
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize("kw", [{}, {"text": "a", "doi": "10.9999/test.1"}, {"text": "x", "section": "funding"},
                                {"sections_text": {"bogus": "x"}}, {"sections_text": {"theory": "  "}},
                                {"doi": "10.1/none"}, {"text": "x" * 200_000}])
def test_bad_requests(index, kw):
    with pytest.raises(QueryError):
        index.similar(**kw)


def test_aliases(index):
    out = index.similar(sections_text={"Methods": "m " * 60, "lit": "t " * 60})
    assert set(out["query"]["sections_compared"]) == {"method", "theory"}


def test_scores_are_rounded(index):
    out = index.similar(text=TEXT, section="theory", k=10)
    for r in out["results"]:
        v = r["similarity"]["by_section"]["theory"]
        assert v["z"] == round(v["z"], 1) and v["percentile"] == round(v["percentile"], 2)


def test_article_lookup(index):
    a = index.article("10.9999/test.4")
    assert a["indexed_sections"] == ["abstract", "introduction", "theory", "discussion"]
    assert np.isscalar(a["year"])


def test_section_ranks(index):
    index.encoder.pin(TEXT, index.V["theory"][9])
    out = index.similar(sections_text={"theory": TEXT, "abstract": "abstract words " * 30}, k=50)
    r9 = next(r for r in out["results"] if r["doi"] == "10.9999/test.9")
    th = r9["similarity"]["by_section"]["theory"]
    assert th["rank"] == 1 and th["of"] == 40 and r9["best_matching_section"] == "theory"
    out = index.similar(doi="10.9999/test.9", k=50)
    ranks = sorted(r["similarity"]["by_section"]["theory"]["rank"] for r in out["results"])
    assert ranks == list(range(1, 40)) and out["results"][0]["similarity"]["by_section"]["theory"]["of"] == 39


def test_section_retrieval_searches_beyond_overall_top_k(index):
    theory, abstract = 'theory query', 'abstract query'
    index.encoder.pin(theory, index.V['theory'][11])
    index.encoder.pin(abstract, index.V['abstract'][32])
    index.sd['abstract'] = 0.00001
    query = {'sections_text': {'theory': theory, 'abstract': abstract}, 'k': 1}
    overall = index.similar(**query)
    section = index.similar(**query, rank_by='theory')
    assert overall['results'][0]['doi'] == '10.9999/test.32'
    assert section['results'][0]['doi'] == '10.9999/test.11'
    assert section['results'][0]['rank'] == 1
    expected = next(r for r in index.similar(sections_text=query['sections_text'], k=50)['results'] if r['doi']=='10.9999/test.11')
    assert section['results'][0]['similarity']['overall_z'] == expected['similarity']['overall_z']


def test_query_cache_reused_across_filters_and_ranking(index):
    count=[0]
    encode=index.encoder.encode
    def counting(text):
        count[0]+=1
        return encode(text)
    index.encoder.encode=counting
    st={'theory':'A theory of status','method':'An empirical analysis'}
    index.similar(sections_text=st)
    index.similar(sections_text=st,rank_by='method',journals=['os'],k=5)
    assert count[0]==2
    assert all(isinstance(k,bytes) for k in index._cache)


def test_doi_does_not_encode_and_ranking_excludes_missing(index):
    def no_encode(text):
        raise AssertionError('DOI searches must not load or call the encoder')
    index.encoder.encode=no_encode
    result=index.similar(doi='10.9999/test.12',rank_by='method',k=50)
    assert all('method' in r['similarity']['by_section'] for r in result['results'])
    assert all(r['doi']!='10.9999/test.12' for r in result['results'])
    with pytest.raises(QueryError):
        index.similar(doi='10.9999/test.4',rank_by='method')


def test_encoder_construction_is_lazy():
    from nearest_prior_work.server.index import BGEM3Encoder
    enc=BGEM3Encoder('not-a-real-model')
    assert enc.model is None and enc.status=='not_loaded'


@pytest.mark.parametrize('cuda,mps,expected', [(True, False, 'cuda'), (False, True, 'mps'), (False, False, 'cpu')])
def test_encoder_automatically_selects_available_device(monkeypatch, cuda, mps, expected):
    import sys
    from types import SimpleNamespace
    from nearest_prior_work.server.index import BGEM3Encoder
    from nearest_prior_work import local
    selected = []
    class Model:
        half_precision = False
        def __init__(self, path, device):
            selected.append(device)
        def half(self):
            self.half_precision = True
    monkeypatch.setitem(sys.modules, 'torch', SimpleNamespace(
        set_num_threads=lambda n: None,
        cuda=SimpleNamespace(is_available=lambda: cuda),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps))))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=Model))
    monkeypatch.setattr(local, 'model_dir', lambda *a, **k: 'local-test-model')
    enc = BGEM3Encoder()
    enc._load()
    assert selected == [expected]
    assert enc.status == 'ready' and enc.model.half_precision == cuda
