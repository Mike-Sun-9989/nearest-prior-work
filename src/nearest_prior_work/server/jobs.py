"""Cancellable model calls in isolated processes. Inputs/results exist only in memory."""
import multiprocessing
import os
import secrets
import subprocess
import threading
import time


def worker(pipe, kind, payload):
    try:
        from ..structure import outline_from_paragraphs, test_model, list_models
        if kind == 'outline':
            result = outline_from_paragraphs(payload['paragraphs'], payload['model'])
            result['file'] = payload['file']
        elif kind == 'test':
            result = test_model(payload['model'])
        elif kind == 'models':
            result = list_models(payload['model'])
        else:
            raise ValueError('Unknown operation.')
        pipe.send({'state': 'done', 'result': result})
    except Exception as e:
        from ..structure import ModelError
        pipe.send({'state': 'error', 'error': str(e) if isinstance(e, ModelError) else
                   'The model request could not finish. Check your settings and retry; your manuscript is unchanged.'})
    finally:
        pipe.close()


def stop_process(process):
    if process.is_alive():
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        else:
            # The worker creates its own session; descendants include the CLI process.
            import signal
            try: os.killpg(process.pid, signal.SIGTERM)
            # No session yet means no descendants, so signalling the worker itself is enough.
            except ProcessLookupError: process.terminate()
        process.join(timeout=5)
        if process.is_alive(): process.kill(); process.join(timeout=5)


def entry(pipe, kind, payload):
    if os.name != 'nt': os.setsid()
    worker(pipe, kind, payload)


class Jobs:
    def __init__(self):
        self.items = {}
        self.lock = threading.RLock()

    def start(self, kind, payload):
        with self.lock:
            self.prune()
            if sum(j['state'] == 'running' for j in self.items.values()) >= 2:
                raise ValueError('Two model requests are already running. Finish or cancel one before trying again.')
            token = secrets.token_urlsafe(24)
            ctx = multiprocessing.get_context('spawn')
            parent, child = ctx.Pipe(duplex=False)
            p = ctx.Process(target=entry, args=(child, kind, payload), daemon=True)
            p.start(); child.close()
            # Only one thread may wait on the worker: a second one can see it reaped and report it as alive.
            stop_lock = threading.Lock()
            self.items[token] = {'state': 'running', 'process': p, 'stop_lock': stop_lock, 'started': time.monotonic()}
        def watch():
            deadline = time.monotonic() + (600 if kind == 'outline' else 90)
            result = None
            try:
                while time.monotonic() < deadline:
                    if parent.poll(.1):
                        result = parent.recv(); break
                    with self.lock:
                        if self.items.get(token, {}).get('state') != 'running': return
                    with stop_lock:
                        alive = p.is_alive()
                    if not alive: break
                if result is None:
                    result = {'state':'error','error':'The model did not reply in time. Check login, connection and model settings, then retry.'}
            except (EOFError, OSError):
                result = {'state':'error','error':'The model request stopped unexpectedly. Check settings and retry.'}
            finally:
                parent.close()
                with stop_lock:
                    p.join(timeout=1)
                    stop_process(p)
            with self.lock:
                if self.items.get(token, {}).get('state') == 'running': self.items[token].update(result)
        threading.Thread(target=watch, daemon=True).start()
        return token

    def get(self, token):
        with self.lock:
            job = self.items.get(token)
            if not job: raise ValueError('This request has expired. Please retry.')
            return {k:v for k,v in job.items() if k not in ('process','stop_lock','started')} | {'seconds':round(time.monotonic()-job['started'])}

    def cancel(self, token):
        with self.lock:
            job = self.items.get(token)
            if not job: return
            job['state'] = 'cancelled'
            job.pop('result', None)
        with job['stop_lock']:
            stop_process(job['process'])
        with self.lock: self.items.pop(token, None)

    def prune(self):
        with self.lock:
            expired = [k for k,v in self.items.items() if v['state'] != 'running' and time.monotonic()-v['started'] > 600]
            for k in expired: self.items.pop(k, None)

    def close(self):
        for token in list(self.items): self.cancel(token)
