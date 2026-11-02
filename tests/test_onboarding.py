import importlib.util
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import httpx
import pytest
from nearest_prior_work import local, structure
from nearest_prior_work.server.preparation import SearchPreparation
from nearest_prior_work.server import jobs as jobs_module
from nearest_prior_work.server.jobs import Jobs
from nearest_prior_work.server import web as web_module
from nearest_prior_work.server.web import build_local_app
from starlette.testclient import TestClient

CFG = {'provider':'custom','model':'demo','api_key':'test-only','base_url':'http://127.0.0.1:9/v1'}


@pytest.mark.parametrize('body', [{}, {'choices':[]}, {'choices':[{'message':{'content':''}}]},
                                 {'choices':[{'message':{'content':[]}}]}, {'choices':[{'message':{'content':'unrelated'}}]}])
def test_connection_requires_valid_reply(body):
    with pytest.raises(structure.ModelError):
        structure.test_model(CFG, httpx.MockTransport(lambda r:httpx.Response(200,json=body)))


@pytest.mark.parametrize('code,word', [(401,'key'),(403,'permissions'),(404,'address'),(429,'allowance'),(503,'later')])
def test_provider_failures_actionable_without_echoing_secrets(code,word):
    with pytest.raises(structure.ModelError) as exc:
        structure.chat(CFG,'s','u',transport=httpx.MockTransport(lambda r:httpx.Response(code,json={'error':'credential-that-must-not-appear'})))
    assert word in str(exc.value) and 'credential-that' not in str(exc.value)


def test_models_list_uses_no_generation():
    calls=[]
    def handler(r):
        calls.append((r.method,r.url.path))
        return httpx.Response(200,json={'data':[{'id':'chat-b'},{'id':'chat-a'}]})
    result=structure.list_models({**CFG,'model':''},httpx.MockTransport(handler))
    assert result['models']==['chat-a','chat-b'] and calls==[('GET','/v1/models')]


def test_preparation_failure_and_retry(monkeypatch):
    attempts=[]
    def download(model,download=True,log=None,progress=None):
        if not download: raise FileNotFoundError()
        attempts.append(1)
        if len(attempts)==1: raise OSError('offline')
        progress(4,4)
        return 'complete'
    monkeypatch.setattr(local,'model_dir',download)
    p=SearchPreparation(SimpleNamespace(model_name='demo'))
    assert p.status()['state']=='needed'
    p.start()
    for _ in range(100):
        if p.status()['state']!='preparing':break
        time.sleep(.01)
    assert p.status()['state']=='error' and 'Retry preparation' in p.status()['message']
    p.start()
    for _ in range(100):
        if p.status()['state']!='preparing':break
        time.sleep(.01)
    assert p.status()['state']=='ready' and p.status()['files_done']==4


def test_missing_search_files_keep_doi_working(index,monkeypatch):
    index.encoder.model_name='uncached'
    monkeypatch.setattr(local,'model_dir',lambda *a,**k:(_ for _ in ()).throw(FileNotFoundError()))
    with TestClient(build_local_app(index),base_url='http://127.0.0.1',client=('127.0.0.1',1)) as c:
        r=c.post('/v1/similar',json={'text':'hello'})
        assert r.status_code==409 and r.json()['action']=='prepare'
        assert c.post('/v1/similar',json={'doi':'10.9999/test.12'}).status_code==200


def test_download_progress_preserves_byte_units(monkeypatch,tmp_path):
    import huggingface_hub
    for name in ('config.json','tokenizer_config.json','model.safetensors'):
        (tmp_path/name).write_text('{}')
    def snapshot(model,**kw):
        if kw.get('local_files_only'): raise FileNotFoundError()
        with kw['tqdm_class'](total=2_000_000,unit='B') as bar:
            bar.update(1_000_000); bar.refresh()
        return str(tmp_path)
    monkeypatch.setattr(huggingface_hub,'snapshot_download',snapshot)
    progress=[]
    local.model_dir('uncached',progress=lambda n,t,u:progress.append((n,t,u)),log=lambda *_:None)
    assert (1_000_000,2_000_000,'bytes') in progress


def test_cli_readiness_does_not_call_generation(monkeypatch):
    calls=[]
    monkeypatch.setattr(structure,'cli_path',lambda p:p)
    def run(cmd,**kw):
        calls.append(cmd)
        text='--ephemeral --ignore-user-config --strict-mcp-config --effort' if '--help' in cmd else (
            '{"loggedIn":true}' if 'auth' in cmd else 'Installed')
        return SimpleNamespace(returncode=0,stdout=text,stderr='')
    monkeypatch.setattr(structure.subprocess,'run',run)
    out=structure.find_clis()
    assert all(x['found'] and x['compatible'] and x['signed_in'] for x in out.values())
    assert not any('-p' in c or '--json' in c and 'exec' in c for c in calls)


def test_installer_selects_platform_source():
    path=Path(__file__).parents[1]/'setup_local.py'
    spec=importlib.util.spec_from_file_location('setup_local_audit',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    assert mod.torch_source('Windows','AMD64',True).endswith('/cu128')
    assert mod.torch_source('Windows','AMD64',False).endswith('/cpu')
    assert mod.torch_source('Darwin','arm64',False)=='https://pypi.org/simple'


def test_bootstrap_selects_supported_python_and_forwards_arguments(monkeypatch):
    path=Path(__file__).parents[1]/'setup_local.py'
    spec=importlib.util.spec_from_file_location('setup_local_versions',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.shutil,'which',lambda name:name)
    monkeypatch.setattr(mod.subprocess,'run',lambda cmd,**kw:SimpleNamespace(returncode=0 if any('3.12' in x for x in cmd[:2]) else 1))
    selected=mod.supported_python()
    assert any('3.12' in x for x in selected)
    monkeypatch.setattr(mod.sys,'version_info',(3,14,0))
    calls=[]
    monkeypatch.setattr(mod.subprocess,'call',lambda cmd:calls.append(cmd) or 0)
    assert mod.main(['--install-only','--port','8840'])==0
    assert calls==[selected+[str(path.resolve()),'--install-only','--port','8840']]


def test_bootstrap_handles_missing_supported_python(monkeypatch):
    path=Path(__file__).parents[1]/'setup_local.py'
    spec=importlib.util.spec_from_file_location('setup_local_missing',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.shutil,'which',lambda name:None)
    assert mod.supported_python() is None


def test_model_jobs_complete_cancel_and_clear():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*a):pass
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if body['model']=='slow':time.sleep(3)
            data=json.dumps({'choices':[{'message':{'content':'OK'}}]}).encode()
            self.send_response(200);self.end_headers()
            try:self.wfile.write(data)
            except OSError:pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    jobs=Jobs()
    try:
        cfg={**CFG,'base_url':f'http://127.0.0.1:{server.server_port}/v1'}
        token=jobs.start('test',{'model':cfg})
        for _ in range(200):
            result=jobs.get(token)
            if result['state']!='running':break
            time.sleep(.05)
        assert result['state']=='done' and result['result']['reply']=='OK'
        jobs.cancel(token)
        assert token not in jobs.items
        token=jobs.start('test',{'model':{**cfg,'model':'slow'}})
        process=jobs.items[token]['process']
        jobs.cancel(token)
        assert not process.is_alive() and token not in jobs.items
    finally:
        jobs.close();server.shutdown();server.server_close()


def test_cancel_right_after_start_reports_the_worker_stopped():
    jobs=Jobs()
    try:
        for _ in range(5):
            token=jobs.start('test',{'model':CFG})
            process=jobs.items[token]['process']
            json.dumps(jobs.get(token))
            jobs.cancel(token)
            assert not process.is_alive() and process.exitcode is not None and token not in jobs.items
    finally:
        jobs.close()


@pytest.mark.skipif(os.name=='nt',reason='Windows stops workers with taskkill')
def test_worker_without_a_session_is_signalled_directly(monkeypatch):
    calls=[]
    class Worker:
        pid=999999
        alive=True
        def is_alive(self):return self.alive
        def terminate(self):calls.append('terminate');self.alive=False
        def kill(self):calls.append('kill')
        def join(self,timeout=None):pass
    def no_group(pid,sig):raise ProcessLookupError()
    monkeypatch.setattr(jobs_module.os,'killpg',no_group)
    jobs_module.stop_process(Worker())
    assert calls==['terminate']


def test_cli_detection_survives_output_the_locale_cannot_decode(monkeypatch):
    # Under a non-UTF-8 Windows locale, undecodable output used to leave stdout empty and raise a raw TypeError.
    seen=[]
    def run(cmd,**kw):
        seen.append(kw)
        return SimpleNamespace(returncode=0,stdout=None,stderr=None)
    monkeypatch.setattr(structure,'cli_path',lambda provider:'agent')
    monkeypatch.setattr(structure.subprocess,'run',run)
    out=structure.find_clis()
    assert all(x['found'] and not x['compatible'] for x in out.values())
    assert seen and all(kw['encoding']=='utf-8' and kw['errors']=='replace' for kw in seen)


def test_setup_guide_is_labelled_and_rechecks_on_return(index):
    with TestClient(build_local_app(index),base_url='http://127.0.0.1',client=('127.0.0.1',1)) as c:
        page,script=c.get('/').text,c.get('/onboarding.js').text
    assert 'id="guide-title">Setup guide' in page and 'Check again now' in page
    assert "addEventListener('focus'" in script and "$('cli-guide').open=!ready" in script


def test_unexpected_type_errors_do_not_reach_the_page(index,monkeypatch):
    def broken():raise TypeError("argument of type 'NoneType' is not iterable")
    monkeypatch.setattr(web_module,'find_clis',broken)
    with TestClient(build_local_app(index),base_url='http://127.0.0.1',client=('127.0.0.1',1)) as c:
        response=c.get('/v1/model/clis')
    assert 'NoneType' not in response.text and response.json()['error']
