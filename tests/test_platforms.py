"""Platform boundaries and fallback checks without a real model or network."""
import importlib.util
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import numpy as np
import pytest


def bootstrap():
    spec = importlib.util.spec_from_file_location('bootstrap_platforms', Path(__file__).parents[1]/'setup_local.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize('system,arch,version,windows_version,ok', [
    ('Windows','AMD64','','10.0.19045',True),  # Windows 10
    ('Windows','AMD64','','10.0.26100',True),  # Windows 11
    ('Windows','AMD64','','6.3.9600',False),
    ('Windows','ARM64','','10.0.26100',False),
    ('Windows','x86','','10.0.19045',False),
    ('Darwin','arm64','14.0','',True),
    ('Darwin','arm64','13.6','',False),
    ('Darwin','x86_64','14.0','',False),
    ('Linux','x86_64','','',False),
    ('Linux','aarch64','','',False),
])
def test_supported_platform_boundaries(system, arch, version, windows_version, ok):
    assert (bootstrap().platform_problem(system,arch,version,windows_version) is None) == ok


def test_partial_environment_can_repair_missing_pip(tmp_path, monkeypatch):
    mod=bootstrap()
    python=tmp_path/'python';python.touch()
    monkeypatch.setattr(mod.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=1))
    calls=[]
    monkeypatch.setattr(mod,'run_logged',lambda cmd,log:calls.append(cmd) or True)
    assert mod.ensure_environment(tmp_path,python,tmp_path/'setup.log')
    assert calls==[[str(python),'-m','ensurepip','--upgrade']]


@pytest.mark.parametrize('system,arch,nvidia,suffix', [
    ('Windows','AMD64',False,'/cpu'),
    ('Windows','AMD64',True,'/cu128'),
    ('Darwin','arm64',False,'/simple'),
])
def test_supported_platform_download_source(system,arch,nvidia,suffix):
    assert bootstrap().torch_source(system,arch,nvidia).endswith(suffix)


def test_emulated_windows_arm_is_rejected(monkeypatch):
    mod=bootstrap()
    monkeypatch.setattr(mod.platform,'system',lambda:'Windows')
    monkeypatch.setattr(mod.platform,'machine',lambda:'AMD64')
    monkeypatch.setenv('PROCESSOR_ARCHITEW6432','ARM64')
    assert 'Windows on ARM' in mod.host_platform_problem()


def test_unsupported_host_stops_before_creating_environment(tmp_path,monkeypatch,capsys):
    mod=bootstrap()
    monkeypatch.setattr(mod,'host_platform_problem',lambda:'Linux is not supported.')
    env=tmp_path/'not-created'
    assert mod.main(['--install-only','--venv',str(env)])==1
    assert not env.exists()
    assert 'Linux is not supported' in capsys.readouterr().out


def test_cpu_setup_does_not_require_cuda_disk_budget(tmp_path,monkeypatch):
    mod=bootstrap()
    monkeypatch.setattr(mod.shutil,'disk_usage',lambda path:SimpleNamespace(free=9*1024**3))
    assert mod.check_space(tmp_path,cpu_only=True)
    assert not mod.check_space(tmp_path,cpu_only=False)


@pytest.mark.parametrize('name,expected',[('posix',True),('nt',False)])
def test_environment_uses_native_venv_link_policy(tmp_path,monkeypatch,name,expected):
    mod=bootstrap();seen=[]
    monkeypatch.setattr(mod,'os',SimpleNamespace(name=name))
    monkeypatch.setattr(mod.venv,'EnvBuilder',lambda **kw:SimpleNamespace(create=lambda path:seen.append(kw)))
    monkeypatch.setattr(mod.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=0))
    assert mod.ensure_environment(tmp_path,tmp_path/'absent',tmp_path/'setup.log')
    assert seen==[{'with_pip':True,'symlinks':expected}]


@pytest.mark.parametrize('device,failure', [('cuda','load'),('mps','load'),('cuda','encode'),('mps','encode'),('mps','nan')])
def test_failed_acceleration_retries_once_on_cpu(monkeypatch,device,failure):
    from nearest_prior_work.server.index import BGEM3Encoder
    from nearest_prior_work import local
    opened=[];batches=[]
    class Model:
        def __init__(self,path,device):
            self.device=device;opened.append(device)
            self.tokenizer=SimpleNamespace(decode=lambda ids:'chunk')
            if device!='cpu' and failure=='load':raise RuntimeError('unavailable device')
        def half(self):pass
        def encode(self,pieces,**kw):
            batches.append(kw['batch_size'])
            if self.device!='cpu' and failure=='encode':raise RuntimeError('out of memory')
            return np.full((len(pieces),4),np.nan if self.device!='cpu' and failure=='nan' else 1,dtype=np.float32)
    class Tokenizer:
        def __call__(self,*a,**k):return {'input_ids':list(range(4500))}
        def decode(self,ids):return 'chunk'
    original_init=Model.__init__
    def init(self,*a,**k):original_init(self,*a,**k);self.tokenizer=Tokenizer()
    Model.__init__=init
    monkeypatch.setitem(sys.modules,'torch',SimpleNamespace(
        set_num_threads=lambda n:None,cuda=SimpleNamespace(is_available=lambda:device=='cuda',empty_cache=lambda:None),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda:device=='mps')),
        mps=SimpleNamespace(empty_cache=lambda:None)))
    monkeypatch.setitem(sys.modules,'sentence_transformers',SimpleNamespace(SentenceTransformer=Model))
    monkeypatch.setattr(local,'model_dir',lambda *a,**k:'local-test')
    encoder=BGEM3Encoder()
    vector,tokens,truncated=encoder.encode('synthetic')
    assert opened==[device,'cpu'] and encoder.device=='cpu'
    assert tokens==4500 and not truncated and np.allclose(np.linalg.norm(vector),1)
    assert batches and all(b==1 for b in batches)
    encoder.encode('again')
    assert opened==[device,'cpu']


def test_cpu_memory_failure_gives_a_recovery_step(monkeypatch):
    from nearest_prior_work.server.index import BGEM3Encoder, QueryError
    encoder=BGEM3Encoder(device='cpu')
    monkeypatch.setattr(encoder,'_load',lambda:None)
    monkeypatch.setattr(encoder,'_encode',lambda text:(_ for _ in ()).throw(RuntimeError("DefaultCPUAllocator: can't allocate memory")))
    with pytest.raises(QueryError,match='Close other apps or try a shorter section'):
        encoder.encode('example')


ROOT = Path(__file__).parents[1]


def launcher_pin(name):
    text = (ROOT/name).read_text(encoding='utf-8')
    return {key: re.search(rf'PY_{key}"?=([^"\r\n]+)', text).group(1) for key in ('RELEASE', 'VERSION', 'SHA256')}


def test_launchers_pin_the_same_private_python():
    windows, mac = launcher_pin('start.bat'), launcher_pin('start.sh')
    assert windows['RELEASE'] == mac['RELEASE'] and windows['VERSION'] == mac['VERSION']
    assert (3, 11) <= tuple(int(x) for x in windows['VERSION'].split('.')[:2]) <= (3, 13)
    assert all(re.fullmatch('[0-9a-f]{64}', x['SHA256']) for x in (windows, mac)) and windows['SHA256'] != mac['SHA256']


def test_launchers_verify_the_download_and_skip_python_stubs():
    bat, sh = (ROOT/'start.bat').read_text(encoding='utf-8'), (ROOT/'start.sh').read_text(encoding='utf-8')
    assert 'certutil.exe" -hashfile' in bat and 'goto bad_download' in bat
    assert 'shasum -a 256' in sh and '!= /usr/bin/python3' in sh
    assert 'PYTHON_MANAGER_AUTOMATIC_INSTALL=false' in bat
    assert '.runtime/' in (ROOT/'.gitignore').read_text(encoding='utf-8')
    assert 'start.sh' in (ROOT/'start.command').read_text(encoding='utf-8')


def test_first_use_instructions_do_not_require_installer_options():
    for name in ('README.md', 'docs/quickstart.md', 'docs/troubleshooting.md', 'setup_local.py', 'start.bat', 'start.sh'):
        assert 'Add Python to PATH' not in (ROOT/name).read_text(encoding='utf-8'), name
