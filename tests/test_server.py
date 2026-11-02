"""Local web workflow, privacy boundary and model failure recovery; no paid calls."""
import base64
import tempfile
from pathlib import Path
import httpx
import pytest
from starlette.testclient import TestClient
from nearest_prior_work.server.app import build_local_app
from nearest_prior_work.server.web import Documents
from model_fixture import fake_model

MODEL = {"provider": "openai", "model": "fake-model", "api_key": "sk-test-not-real"}
MD = b'# A Study of Firms\n\nAbstract: Firms learn from networks.\n\n# Introduction\n\nNetworks connect firms.\n\n# Theory\n\nStatus signals partner quality.\n\n# Methods\n\nWe estimate a model.\n\n# References\n\nA.'


def client(app):
    return TestClient(app, base_url="http://127.0.0.1:8800", client=("127.0.0.1", 12345))


@pytest.fixture()
def web(index):
    calls = []
    with client(build_local_app(index, model_transport=fake_model(calls))) as c:
        yield c, calls


def inspect(c, name="draft.md", content=MD):
    return c.post('/v1/inspect', json={"filename": name, "data_b64": base64.b64encode(content).decode()})


def test_local_start_and_doi_need_no_model(web):
    c, calls = web
    page = c.get('/')
    assert page.status_code == 200 and 'frame-ancestors' in page.headers['content-security-policy']
    assert 'BGE' not in page.text and 'GPU' not in page.text and 'CPU' not in page.text
    assert c.get('/v1/health').json()['mode'] == 'local'
    out = c.post('/v1/similar', json={"doi": "10.9999/test.12", "rank_by": "theory", "k": 5})
    assert out.status_code == 200 and out.json()['query']['rank_by'] == 'theory'
    assert out.json()['n_results'] == 5 and not calls
    assert c.post('/mcp', json={}).status_code == 404


@pytest.mark.parametrize('headers', [
    {'Host': 'example.com'}, {'Origin': 'https://example.com'},
    {'Origin': 'null'}, {'Origin': 'http://127.0.0.1:9999'}, {'Sec-Fetch-Site': 'cross-site'}])
def test_browser_boundary(web, headers):
    c, calls = web
    assert c.post('/v1/model/test', json={"model": MODEL}, headers=headers).status_code == 403
    assert not calls


def test_remote_peer_rejected(index):
    with TestClient(build_local_app(index), base_url='http://127.0.0.1:8800', client=('192.168.1.2', 22)) as c:
        assert c.get('/v1/health').status_code == 403


def test_manuscript_inspect_identify_review_search(web):
    c, calls = web
    before = set(Path(tempfile.gettempdir()).glob('npw_*'))
    r = inspect(c)
    assert r.status_code == 200, r.text
    doc = r.json()
    assert doc['words'] > 0 and 'Firms learn from networks' in doc['preview'] and not calls
    assert set(Path(tempfile.gettempdir()).glob('npw_*')) == before
    r = c.post('/v1/outline', json={'document_id': doc['document_id'], 'model': MODEL})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out['file'] == 'draft.md' and len(calls) == 1
    sections = {h['section']: h['text'] for h in out['headings'] if h['section'] in ('theory', 'method')}
    result = c.post('/v1/similar', json={'sections_text': sections, 'rank_by': 'theory'})
    assert result.status_code == 200 and len(calls) == 1
    assert 'api_key' not in str(result.json()) and 'Status signals' not in str(result.json())
    assert c.delete('/v1/document/' + doc['document_id']).status_code == 204
    assert c.post('/v1/outline', json={'document_id': doc['document_id'], 'model': MODEL}).status_code == 400
    assert len(calls) == 1


def test_identification_failure_retains_document(index):
    calls=[]
    good = fake_model(calls)
    count=[0]
    def handler(request):
        count[0] += 1
        if count[0] == 1:
            return httpx.Response(429, json={'error': {'message': 'Allowance exhausted'}})
        return good.handle_request(request)
    with client(build_local_app(index, model_transport=httpx.MockTransport(handler))) as c:
        doc=inspect(c).json()
        body={'document_id': doc['document_id'], 'model': MODEL}
        first=c.post('/v1/outline',json=body)
        assert first.status_code==400 and 'allowance' in first.json()['error']
        assert c.post('/v1/outline',json=body).status_code==200


def test_docx_and_bad_uploads(web):
    c, calls=web
    path=Path(__file__).parent.parent/'examples/demo_manuscript.docx'
    assert inspect(c,path.name,path.read_bytes()).status_code==200
    for name,content in [('a.exe',b'abc'),('a.md',b''),('a.docx',b'invalid')]:
        assert inspect(c,name,content).status_code==400
    assert not calls


def test_same_origin_model_test(web):
    c,calls=web
    r=c.post('/v1/model/test',json={'model':MODEL},headers={'Origin':'http://127.0.0.1:8800'})
    assert r.status_code==200 and r.json()['reply']=='OK' and len(calls)==1


def test_documents_expire_and_are_bounded(monkeypatch):
    clock=[100.0]
    monkeypatch.setattr('nearest_prior_work.server.web.time.monotonic',lambda:clock[0])
    docs=Documents()
    first=docs.put('a',[{'text':'a'}])
    for i in range(4): docs.put(str(i),[])
    assert first not in docs.items and len(docs.items)==4
    clock[0]+=1801
    docs.prune()
    assert not docs.items


def test_doi_page_states_coverage_and_recovers_from_a_miss(web):
    c, calls = web
    health = c.get('/v1/health').json()
    assert sum(x['articles'] for x in health['coverage']) == health['articles']
    assert {x['journal'] for x in health['coverage']} == set(health['journals'])
    assert all(1996 <= x['year_min'] <= x['year_max'] <= 2026 for x in health['coverage'])
    page = c.get('/').text
    assert 'id="coverage-rows"' in page and 'Not every article in these journals is included' in page
    out = c.post('/v1/similar', json={"doi": "10.9999/missing"})
    assert out.status_code == 404 and out.json()['action'] == 'paste' and 'not in the local index' in out.json()['error']
    assert c.post('/v1/similar', json={"doi": "https://doi.org/10.9999/TEST.12"}).status_code == 200
    assert not calls


def test_page_starts_preparation_only_when_it_has_not_failed(web):
    c, _ = web
    script = c.get('/onboarding.js').text
    assert "if(p.state==='needed')$('prepare').onclick();" in script
    assert "$('prepare').classList.toggle('hidden', p.state !== 'error');" in script


def test_section_choice_is_offered_before_searching(web):
    c, _ = web
    page = c.get('/').text
    assert page.index('id="prerank"') < page.index('id="search"') < page.index('id="rankby"')
    assert 'All sections (average)' in page and 'Overall similarity' not in page


def test_section_choice_searches_beyond_the_average_ranking(web):
    c, _ = web
    average = c.post('/v1/similar', json={"doi": "10.9999/test.12", "k": 5}).json()
    theory = c.post('/v1/similar', json={"doi": "10.9999/test.12", "k": 5, "rank_by": "theory"}).json()
    assert theory['query']['rank_by'] == 'theory' and average['query']['rank_by'] == 'overall'
    ranks = [r['similarity']['by_section']['theory']['rank'] for r in theory['results']]
    assert ranks == list(range(1, 6))


def test_article_without_the_chosen_section_is_explained(web):
    c, _ = web
    out = c.post('/v1/similar', json={"doi": "10.9999/test.3", "rank_by": "method"})
    assert out.status_code == 400 and 'no indexed Method section' in out.json()['error']
