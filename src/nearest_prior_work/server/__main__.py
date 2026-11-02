"""Start the local application. No public hosting or application API keys."""
import argparse
import hashlib
import json
import socket
import os
import threading
import urllib.request
import time
import webbrowser


def existing_app(url, identity):
    from .. import __version__
    try:
        with urllib.request.urlopen(url + '/v1/health', timeout=.25) as r:
            data = json.load(r)
        return data.get('app_id') == 'nearest-prior-work' and data.get('version') == __version__ and data.get('instance') == identity
    except (OSError, ValueError):
        return False


def main(argv=None):
    ap = argparse.ArgumentParser(prog="npw", description="Open Nearest Prior Work on this computer")
    ap.add_argument("command", nargs="?", choices=["serve"], help=argparse.SUPPRESS)
    ap.add_argument("--port", type=int, default=8800)
    ap.add_argument("--no-open", action="store_true", help="do not open a browser")
    ap.add_argument("--prepare", action="store_true", help="prepare local text search for use without an internet connection")
    ap.add_argument("--db", help=argparse.SUPPRESS)
    ap.add_argument("--model", default="BAAI/bge-m3", help=argparse.SUPPRESS)
    ap.add_argument("--device", choices=["cpu", "cuda", "mps"], help=argparse.SUPPRESS)
    ap.add_argument("--web", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--open", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--no-auth", action="store_true", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    from ..local import find_db, prefetch_model
    from .index import BGEM3Encoder, Index
    from .app import build_local_app
    import uvicorn
    if a.prepare:
        prefetch_model(a.model, log=lambda *_: print("Preparing local text search…", flush=True))
        print("Local text search files are ready.")
        return
    db = find_db(a.db)
    identity = hashlib.sha256((os.path.realpath(db) + '|' + a.model + '|' + str(a.device)).encode()).hexdigest()[:24]
    selected = None
    for port in range(a.port, min(a.port + 20, 65536)):
        url = f"http://127.0.0.1:{port}"
        if existing_app(url, identity):
            if selected: selected[1].close()
            print(f"Nearest Prior Work is already running. Open {url}", flush=True)
            if not a.no_open: webbrowser.open(url)
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(('127.0.0.1', port))
            if selected is None: selected = (port, sock)
            else: sock.close()
        except OSError:
            sock.close()
    if selected is None:
        print('No local address is available. Close an unused local app, or start with --port 8900.')
        raise SystemExit(1)
    port, sock = selected
    url = f"http://127.0.0.1:{port}"
    try:
        print('Opening your local collection...', flush=True)
        idx = Index(db, BGEM3Encoder(a.model, a.device))
        idx.instance_id = identity
        sock.listen(128)
        if not a.no_open:
            def open_when_ready():
                for _ in range(150):
                    if existing_app(url, identity):
                        webbrowser.open(url)
                        return
                    time.sleep(.2)
            threading.Thread(target=open_when_ready, daemon=True).start()
        print(f"Nearest Prior Work: {url}. Keep this window open while using the app.", flush=True)
        uvicorn.Server(uvicorn.Config(build_local_app(idx), host='127.0.0.1', port=port, log_level='warning')).run(sockets=[sock])
    finally:
        sock.close()


if __name__ == "__main__":
    main()
