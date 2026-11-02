"""Standard-library bootstrap. User-facing messages omit implementation details."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import venv

ROOT = Path(__file__).resolve().parent
TORCH = '2.11.0'


def platform_problem(system, machine, mac_version='', windows_version=''):
    arch = machine.lower()
    if system == 'Darwin':
        if arch != 'arm64':
            return 'This release requires an Apple silicon Mac and native Apple silicon Python. Intel Macs and Python running under Rosetta are not supported.'
        if mac_version and tuple(int(p) for p in mac_version.split('.')[:1]) < (14,):
            return 'This release requires macOS 14 or later. Update macOS before installing.'
    elif system == 'Windows':
        if arch not in ('amd64', 'x86_64'):
            return 'This release requires Windows 10 or 11 on an x64 computer. Windows on ARM is not supported.'
        # Both Windows 10 and 11 use kernel version 10; CI Windows Server does too.
        if windows_version and int(windows_version.split('.')[0]) < 10:
            return 'This release requires Windows 10 or 11. Update Windows before installing.'
    else:
        return 'This release supports Windows 10/11 on x64 computers and Apple silicon Macs. Linux is not supported.'
    return None


def host_platform_problem():
    system = platform.system()
    # An x64 Python can run under emulation on Windows ARM. Check the native host.
    machine = (os.environ.get('PROCESSOR_ARCHITEW6432') or platform.machine()) if system == 'Windows' else platform.machine()
    return platform_problem(system, machine, platform.mac_ver()[0], platform.win32_ver()[1])


def ensure_environment(env, python, log):
    try:
        if not python.is_file():
            venv.EnvBuilder(with_pip=True, symlinks=os.name != 'nt').create(env)
        # An interrupted setup can leave python behind without pip. Repair it on retry.
        if subprocess.run([str(python), '-m', 'pip', '--version'], capture_output=True).returncode:
            if not run_logged([str(python), '-m', 'ensurepip', '--upgrade'], log):
                raise RuntimeError('pip unavailable')
        return True
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        with log.open('a',encoding='utf-8') as output:
            output.write(f'Environment creation failed: {error!r}\n')
        print('The application environment could not be created. Reinstall Python with pip included, then retry. '
              f'Use a writable extracted folder; do not run this launcher with sudo. Details: {log}')
        return False


def supported_python():
    """Find a supported interpreter even when the default is newer or older."""
    candidates = ([['py', '-3.13'], ['py', '-3.12'], ['py', '-3.11']] if os.name == 'nt' else [])
    candidates += [[name] for name in ('python3.13', 'python3.12', 'python3.11', 'python3', 'python')]
    code = 'import sys;sys.exit(not ((3,11)<=sys.version_info[:2]<=(3,13) and sys.maxsize>2**32))'
    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            if subprocess.run(cmd + ['-c', code], capture_output=True, timeout=10).returncode == 0:
                return cmd
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def check_space(env, cpu_only=False):
    # pip's temporary/cache files and the encoder cache can live on another drive.
    required = 8 if cpu_only else 15
    locations = [(env, required), (Path(tempfile.gettempdir()), 3 if cpu_only else 6),
                 (Path(os.environ.get('HF_HOME', Path.home()/'.cache'/'huggingface')), 3)]
    for path, gib in locations:
        while not path.exists(): path = path.parent
        if shutil.disk_usage(path).free < gib * 1024**3:
            print(f'There is not enough free space for setup. Allow at least {required} GB for the app, downloads and search files, '
                  'including space on your system drive, then retry.')
            return False
    return True


def nvidia_available():
    try:
        r = subprocess.run(['nvidia-smi', '--query-gpu=name', '--format=csv,noheader'], capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and bool(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return False


def torch_source(system, machine, nvidia):
    if system == 'Windows' and machine.lower() in ('amd64', 'x86_64'):
        return 'https://download.pytorch.org/whl/' + ('cu128' if nvidia else 'cpu')
    return 'https://pypi.org/simple'


def run_logged(cmd, log):
    with log.open('a', encoding='utf-8') as f:
        p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        started = time.monotonic()
        try:
            while p.poll() is None:
                time.sleep(1)
                if time.monotonic() - started >= 25:
                    print('Still preparing. Please keep this window open.', flush=True)
                    started = time.monotonic()
        except KeyboardInterrupt:
            p.terminate(); p.wait()
            raise
        return p.returncode == 0


def probe(python):
    code = ('import json,torch; c=torch.cuda.is_available(); '
            'x=torch.ones(1,device="cuda" if c else "cpu"); '
            'print(json.dumps({"cuda":c,"version":torch.__version__}))')
    try:
        r = subprocess.run([str(python), '-c', code], capture_output=True, text=True, timeout=90)
        return json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def main(argv=None):
    ap = argparse.ArgumentParser(description='Set up and open Nearest Prior Work')
    ap.add_argument('--install-only', action='store_true')
    ap.add_argument('--venv', type=Path, default=ROOT / '.venv', help=argparse.SUPPRESS)
    ap.add_argument('--no-open', action='store_true')
    ap.add_argument('--port', type=int, default=8800)
    ap.add_argument('--cpu', action='store_true', help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not (3, 11) <= sys.version_info[:2] <= (3, 13) or sys.maxsize <= 2**32:
        selected = supported_python()
        if selected:
            print('Opening setup with a supported Python installation...', flush=True)
            return subprocess.call(selected + [str(Path(__file__).resolve()), *(sys.argv[1:] if argv is None else argv)])
        print('This Python version is not supported. Open start.bat (Windows) or start.command (macOS) instead; '
              'it sets up a suitable private Python automatically.')
        return 1
    problem = host_platform_problem()
    if problem:
        print(problem)
        return 1
    env = args.venv.resolve()
    env.mkdir(parents=True, exist_ok=True)
    python = env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    log, stamp = env / 'setup.log', env / 'npw-setup.json'
    digest = hashlib.sha256(b''.join((ROOT / p).read_bytes() for p in
                                   ('setup_local.py', 'pyproject.toml', 'constraints.txt')) + str(args.cpu).encode()).hexdigest()
    with (env / 'setup.lock').open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print('Setup is already running. Return to the first setup window and wait for it to finish.')
            return 1
        try:
            saved = json.loads(stamp.read_text())
        except (OSError, ValueError):
            saved = {}
        if saved.get('fingerprint') != digest or not python.is_file():
            accelerated = not args.cpu and nvidia_available()
            source = torch_source(platform.system(), platform.machine(), accelerated)
            accelerated = source.endswith('/cu128')
            if not check_space(env, cpu_only=not accelerated):
                return 1
            print('Step 1 of 3: preparing the application environment...', flush=True)
            if python.is_file() and subprocess.run([str(python), '-c', 'import sys;sys.exit(not ((3,11)<=sys.version_info[:2]<=(3,13)))']).returncode:
                print('This folder contains an incompatible environment. Rename .venv to .venv-old and restart.')
                return 1
            if not ensure_environment(env, python, log):
                return 1
            if subprocess.run([str(python), '-c', 'import sys;sys.exit(any("site-packages" in p and not p.startswith(sys.prefix) for p in sys.path))'],
                              capture_output=True).returncode:
                print('This old environment shares packages with other software. Rename .venv to .venv-old and restart for an independent installation.')
                return 1
            print('Step 2 of 3: installing search components. First setup downloads several GB; keep internet connected.', flush=True)
            pip = [str(python), '-m', 'pip', 'install', '--disable-pip-version-check', '--timeout', '60', '--retries', '3']
            if not run_logged(pip + ['--upgrade', f'torch=={TORCH}', '--index-url', source], log):
                print(f'Download did not finish. Check internet access and disk space, then restart. Details: {log}')
                return 1
            device = probe(python)
            if not device or (accelerated and not device['cuda']):
                print('Using the standard processing option for this computer.', flush=True)
                if not run_logged(pip + ['--force-reinstall', f'torch=={TORCH}', '--index-url',
                                          torch_source(platform.system(), platform.machine(), False)], log) or not probe(python):
                    print(f'Search components could not start. Check system updates and restart. Details: {log}')
                    return 1
            print('Step 3 of 3: installing and checking the application...', flush=True)
            if not run_logged(pip + ['-c', str(ROOT / 'constraints.txt'), '-e', str(ROOT)], log):
                print(f'Installation did not finish. Check internet access and restart to retry. Details: {log}')
                return 1
            if not run_logged([str(python), '-m', 'pip', 'check'], log):
                print(f'The environment needs repair. Rename .venv to .venv-old, then restart. Details: {log}')
                return 1
            stamp.write_text(json.dumps({'fingerprint': digest}), encoding='utf-8')
            print('Installation complete.', flush=True)
    if args.install_only:
        return 0
    cmd = [str(python), '-m', 'nearest_prior_work.server', '--port', str(args.port)]
    if args.no_open:
        cmd.append('--no-open')
    if args.cpu:
        cmd.extend(['--device', 'cpu'])
    return subprocess.call(cmd)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print('\nSetup stopped. Start again to retry.')
        sys.exit(1)
    except OSError as e:
        print(f'Setup could not access a required file ({type(e).__name__}). Extract the repository to a writable local folder and retry.')
        sys.exit(1)
