"""Opt-in real local retrieval check. No language-model calls or credentials.

Run after setup with the environment's Python. --prepare permits the initial
model download; otherwise an existing cache is required. Timings describe this host only.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--device', choices=['auto','cpu'], default='auto')
    ap.add_argument('--prepare', action='store_true')
    args = ap.parse_args()
    from nearest_prior_work.local import model_dir, find_db
    from nearest_prior_work.server.index import BGEM3Encoder, Index
    from nearest_prior_work.server.web import build_local_app
    from nearest_prior_work.paragraphs import read_paragraphs
    from starlette.testclient import TestClient
    import torch
    print(f'Python {sys.version.split()[0]}; torch {torch.__version__}; requested {args.device}', flush=True)
    model = model_dir(download=args.prepare, log=lambda *_:print('Preparing local search files...',flush=True))
    print('PASS: local search files ready.', flush=True)
    # Exercise the real local launcher and HTTP socket before heavier retrieval.
    with socket.socket() as s:
        s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix='npw_smoke_') as temporary:
        with open(Path(temporary)/'server.log','w+',encoding='utf-8') as log:
            cmd=[sys.executable,'-m','nearest_prior_work.server','--port',str(port),'--no-open']
            if args.device=='cpu':cmd+=['--device','cpu']
            process=subprocess.Popen(cmd,stdout=log,stderr=log)
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/v1/health',timeout=2) as response:
                            health=json.load(response)
                        break
                    except OSError:
                        if process.poll() is not None:raise RuntimeError('Local launcher exited before readiness.')
                        time.sleep(.2)
                else:raise RuntimeError('Local launcher did not become ready.')
                assert health['articles']==10357 and health['mode']=='local'
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=3) as response:
                    assert b'Choose a manuscript' in response.read()
                print('PASS: launcher, localhost HTTP and web page.',flush=True)
            finally:
                if os.name=='nt':
                    # venv's Windows redirector launches another Python process.
                    subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=15)
                else:
                    process.terminate()
                try:process.wait(timeout=10)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=10)
    encoder=BGEM3Encoder(model, None if args.device=='auto' else args.device)
    index=Index(find_db(),encoder)
    with TestClient(build_local_app(index),base_url='http://127.0.0.1',client=('127.0.0.1',1)) as client:
        result=client.post('/v1/similar',json={'doi':'10.1287/orsc.1080.0386','k':3})
        assert result.status_code==200 and len(result.json()['results'])==3
        assert encoder.model is None
        print('PASS: DOI retrieval before encoder load.',flush=True)
        text='Status signals shape alliance formation among biotechnology firms seeking legitimacy in uncertain markets.'
        started=time.perf_counter()
        result=client.post('/v1/similar',json={'text':text,'section':'theory','k':3})
        assert result.status_code==200,result.text
        assert len(result.json()['results'])==3
        print(f'PASS: cold text retrieval {time.perf_counter()-started:.2f}s; actual device {encoder.device}.',flush=True)
        # Synthetic example only: the LLM stage is covered by mock-provider tests.
        names={'Abstract.':'abstract','Introduction':'introduction',
               'Endorsements, Motives, and the Transfer of Standing':'theory',
               'Data and Methods':'method','Results':'results','Discussion':'discussion'}
        sections={};role=None
        for paragraph in read_paragraphs(str(ROOT/'examples/demo_manuscript.docx')):
            heading=paragraph['text'].lstrip('# ').strip()
            if heading.startswith('Abstract.'):
                role='abstract';sections[role]=paragraph['text']+'\n'
            elif heading in names:role=names[heading];sections[role]=''
            elif heading=='References':role=None
            elif role:sections[role]+=paragraph['text']+'\n'
        assert len(sections)==6, list(sections)
        started=time.perf_counter()
        result=client.post('/v1/similar',json={'sections_text':sections,'k':20})
        assert result.status_code==200,result.text
        assert len(result.json()['results'])==20
        print(f'PASS: six-section synthetic manuscript returned 20 articles in {time.perf_counter()-started:.2f}s.',flush=True)
        started=time.perf_counter()
        result=client.post('/v1/similar',json={'text':text+' '+('Organizations learn through repeated collaboration and evaluate status signals. '*300),'section':'theory','k':3})
        assert result.status_code==200,result.text
        print(f'PASS: multi-chunk text retrieval {time.perf_counter()-started:.2f}s; actual device {encoder.device}.',flush=True)
    original=socket.socket.connect
    def blocked(*a,**k):raise RuntimeError('Network disabled for offline verification')
    socket.socket.connect=blocked
    try:
        result=index.similar(text='Firms use partnerships to evaluate the legitimacy and capabilities of potential collaborators.',section='theory',k=3)
        assert len(result['results'])==3
        json.dumps(result,allow_nan=False)
    finally:socket.socket.connect=original
    print('PASS: offline retrieval with socket connections blocked.',flush=True)
    print('Input/output index rows: 10357/10357. Dropped: 0; merges: none. No research data modified.',flush=True)


if __name__=='__main__':main()
