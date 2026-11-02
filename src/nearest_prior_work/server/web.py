"""Loopback-only browser application. No public service, accounts or application keys."""
import base64
import binascii
import json
import os
import secrets
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from importlib import resources
from urllib.parse import urlsplit

import anyio
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Route

from .. import __version__
from ..manuscript import SUPPORTED
from ..paragraphs import read_paragraphs
from ..structure import ModelError, find_clis, outline_from_paragraphs, test_model
from .index import DOINotIndexed, QueryError

MAX_UPLOAD = 20_000_000
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class LocalBoundary:
    """Reject non-loopback hosts, remote peers, and cross-origin browser requests."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            host = headers.get(b"host", b"").decode("latin1")
            origin = headers.get(b"origin", b"").decode("latin1")
            try:
                hostname = urlsplit("http://" + host).hostname
                same_origin = not origin or origin == f"http://{host}"
            except ValueError:
                hostname, same_origin = None, False
            peer = (scope.get("client") or (None,))[0]
            allowed = hostname in LOCAL_HOSTS and peer in LOCAL_HOSTS and same_origin
            if headers.get(b"sec-fetch-site") == b"cross-site":
                allowed = False
            if not allowed:
                return await JSONResponse({"error": "Open this app on this computer using its local address."}, 403)(scope, receive, send)
        await self.app(scope, receive, send)


class Documents:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()

    def prune(self):
        with self.lock:
            now = time.monotonic()
            self.items = {k: v for k, v in self.items.items() if now - v[0] < 1800}

    def put(self, name, pars):
        self.prune()
        with self.lock:
            if len(self.items) >= 4:
                self.items.pop(next(iter(self.items)))
            token = secrets.token_urlsafe(24)
            self.items[token] = (time.monotonic(), name, pars)
            return token

    def get(self, token):
        self.prune()
        if not isinstance(token, str):
            raise QueryError("Choose a manuscript before identifying sections.")
        with self.lock:
            item = self.items.get(token)
            if item is None:
                raise QueryError("This file has expired. Choose it again; no model call has been made.")
            return item[1:]

    def discard(self, token):
        with self.lock:
            self.items.pop(token, None)


def build_local_app(index, model_transport=None):
    from .preparation import SearchPreparation
    from .jobs import Jobs
    docs = Documents()
    preparation, jobs = SearchPreparation(index.encoder), Jobs()
    page = resources.files(__package__).joinpath("static", "index.html").read_text(encoding="utf-8")

    async def payload(request, limit=2_000_000):
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > limit:
                raise QueryError("This file or request is too large. Choose a file under 20 MB, or paste a section.")
        obj = json.loads(raw or b"{}")
        if not isinstance(obj, dict):
            raise QueryError("Expected a JSON object.")
        return obj

    def route(fn):
        async def guarded(request):
            try:
                return await fn(request)
            except (QueryError, ModelError, ValueError, TypeError) as e:
                return JSONResponse({"error": str(e)}, 400, headers={"Cache-Control": "no-store"})
            except Exception:
                # Never echo provider bodies, credentials, paths or manuscript text.
                return JSONResponse({"error": "The local operation could not finish. Your input is still available. Retry, or restart the app if this continues."}, 500)
        return guarded

    @route
    async def home(request):
        from .app import PAGE_CSP
        return HTMLResponse(page, headers={"Content-Security-Policy": PAGE_CSP, "Cache-Control": "no-store",
                                           "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"})

    @route
    async def onboarding(request):
        js = resources.files(__package__).joinpath('static', 'onboarding.js').read_text(encoding='utf-8')
        return Response(js, media_type='application/javascript', headers={'Cache-Control':'no-store'})

    @route
    async def health(request):
        return JSONResponse({"ok": True, 'app_id':'nearest-prior-work', "version": __version__, "mode": "local",
                             'instance':getattr(index,'instance_id',''), 'preparation':preparation.status(), **index.info()})

    @route
    async def prepare(request):
        if request.method == 'POST': preparation.start()
        return JSONResponse(preparation.status(), headers={'Cache-Control':'no-store'})

    @route
    async def similar(request):
        from .app import SIMILAR_ARGS
        data = await payload(request)
        if set(data) - SIMILAR_ARGS:
            raise QueryError("Unknown search fields.")
        if not data.get('doi') and preparation.status()['state'] != 'ready':
            return JSONResponse({'error':'Local search is not ready yet. Wait for preparation to finish, then retry. Your input is unchanged.', 'action':'prepare'}, 409)
        try:
            result = await anyio.to_thread.run_sync(lambda: index.similar(**data))
        except DOINotIndexed:
            return JSONResponse({'error':'This DOI is not in the local index. The paper may be from another journal, '
                                         'or from a listed journal but not included. You can still compare it by pasting its abstract or a section.',
                                 'action':'paste'}, 404, headers={'Cache-Control':'no-store'})
        except QueryError:
            raise
        except Exception:
            preparation.failed()
            return JSONResponse({'error':preparation.status()['message'], 'action':'prepare'}, 503)
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @route
    async def article(request):
        data = await payload(request)
        return JSONResponse(index.article(data.get("doi")))

    @route
    async def inspect(request):
        data = await payload(request, MAX_UPLOAD * 4 // 3 + 10_000)
        name = str(data.get("filename") or "").replace("\\", "/").split("/")[-1]
        ext = os.path.splitext(name)[1].lower()
        if ext not in SUPPORTED:
            raise QueryError("Choose a Word, PDF, Markdown, LaTeX or plain text file.")
        try:
            raw = base64.b64decode(data.get("data_b64") or "", validate=True)
        except (ValueError, binascii.Error):
            raise QueryError("The file could not be read. Choose it again.")
        if not raw or len(raw) > MAX_UPLOAD:
            raise QueryError("Choose a non-empty file under 20 MB.")

        def read():
            fd, path = tempfile.mkstemp(prefix="npw_", suffix=ext)
            try:
                with os.fdopen(fd, "wb") as f:
                    f.write(raw)
                return read_paragraphs(path)
            except Exception:
                raise QueryError("No readable text could be extracted. For scanned PDFs, use a text-based PDF or Word file; for protected files, use an unlocked copy.") from None
            finally:
                os.remove(path)
        pars = await anyio.to_thread.run_sync(read)
        count = sum(len(p["text"].split()) for p in pars)
        if not count:
            raise QueryError("No text was found. Use a text-based PDF or Word file.")
        return JSONResponse({"document_id": docs.put(name, pars), "file": name, "words": count,
                             "paragraphs": len(pars), "preview": "\n\n".join(p["text"] for p in pars[:5])[:2000]})

    @route
    async def outline(request):
        data = await payload(request)
        name, pars = docs.get(data.get("document_id"))
        out = await anyio.to_thread.run_sync(lambda: outline_from_paragraphs(pars, data.get("model"), model_transport))
        out["file"] = name
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    @route
    async def discard(request):
        docs.discard(request.path_params["token"])
        return Response(status_code=204)

    @route
    async def clis(request):
        return JSONResponse({"clis": await anyio.to_thread.run_sync(find_clis)})

    @route
    async def model_test(request):
        data = await payload(request)
        return JSONResponse(await anyio.to_thread.run_sync(lambda: test_model(data.get("model"), model_transport)))

    @route
    async def start_job(request):
        data = await payload(request)
        kind = data.get('kind')
        if kind not in ('outline','test','models'): raise QueryError('Unknown model operation.')
        from ..structure import check_config
        cfg = data.get('model')
        check_config({**(cfg or {}), 'model':(cfg or {}).get('model') or ('_list_' if kind == 'models' else '')})
        job_data = {'model':cfg}
        if kind == 'outline':
            name, pars = docs.get(data.get('document_id'))
            job_data.update(file=name, paragraphs=pars)
        token = jobs.start(kind, job_data)
        return JSONResponse({'job_id':token}, status_code=202, headers={'Cache-Control':'no-store'})

    @route
    async def job_status(request):
        token = request.path_params['token']
        if request.method == 'DELETE':
            await anyio.to_thread.run_sync(lambda:jobs.cancel(token))
            return Response(status_code=204)
        return JSONResponse(jobs.get(token), headers={'Cache-Control':'no-store'})

    @asynccontextmanager
    async def lifespan(app):
        async def clean():
            while True:
                await anyio.sleep(60)
                docs.prune()
                jobs.prune()
        async with anyio.create_task_group() as group:
            group.start_soon(clean)
            yield
            group.cancel_scope.cancel()
        docs.items.clear()
        jobs.close()

    app = Starlette(routes=[Route("/", home), Route('/onboarding.js',onboarding), Route("/v1/health", health),
        Route("/v1/similar", similar, methods=["POST"]), Route("/v1/article", article, methods=["POST"]),
        Route("/v1/inspect", inspect, methods=["POST"]), Route("/v1/outline", outline, methods=["POST"]),
        Route("/v1/document/{token}", discard, methods=["DELETE"]), Route("/v1/model/clis", clis),
        Route("/v1/model/test", model_test, methods=["POST"]), Route('/v1/preparation',prepare,methods=['GET','POST']),
        Route('/v1/jobs',start_job,methods=['POST']), Route('/v1/jobs/{token}',job_status,methods=['GET','DELETE'])], lifespan=lifespan)
    return LocalBoundary(app)
