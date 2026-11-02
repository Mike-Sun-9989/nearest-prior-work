"""
Search the bundled index on this computer. Queries are embedded locally with BGE-M3.
The legacy package installer remains an internal migration utility, not a product entry point.
"""
import hashlib
import json
import os
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path

from .client import ServerError

DATA_ROOT = os.path.join(os.path.expanduser("~"), ".nearest-prior-work", "data")
MODEL = "BAAI/bge-m3"
BUNDLED_DB = Path(__file__).parent / "data"


def find_db(path=None):
    """Explicit path/environment, bundled index, then a previously installed local package."""
    path = path or os.environ.get("NPW_LOCAL_DB")
    if path:
        if not os.path.isfile(os.path.join(path, "manifest.json")):
            raise ServerError(f"no data package in {path} (manifest.json missing)")
        return path
    if (BUNDLED_DB / "manifest.json").is_file():
        return str(BUNDLED_DB)
    found = sorted(d for d in (os.listdir(DATA_ROOT) if os.path.isdir(DATA_ROOT) else [])
                   if os.path.isfile(os.path.join(DATA_ROOT, d, "manifest.json")))
    if not found:
        raise ServerError("The bundled article index is missing. Restore the repository data folder or reinstall the complete package.")
    return os.path.join(DATA_ROOT, found[-1])


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def install_data(src, root=DATA_ROOT, log=print):
    """Install the data package from a local zip or a URL; check every file against the manifest's hashes."""
    os.makedirs(root, exist_ok=True)
    tmp = None
    if src.startswith(("http://", "https://")):
        import httpx
        fd, tmp = tempfile.mkstemp(suffix=".zip")
        os.close(fd)
        log(f"downloading {src}")
        with httpx.stream("GET", src, follow_redirects=True, timeout=120) as r:
            r.raise_for_status()
            total, done, last = int(r.headers.get("content-length", 0)), 0, 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 2:
                        log(f"  {done / 1e6:.0f} MB" + (f" of {total / 1e6:.0f} MB" if total else ""))
                        last = time.time()
        src = tmp
    try:
        with zipfile.ZipFile(src) as z:
            names = z.namelist()
            top = {n.split("/")[0] for n in names}
            if len(top) != 1 or any(".." in n or n.startswith("/") for n in names):
                raise ServerError("unexpected layout in the data package zip")
            name = top.pop()
            dest = os.path.join(root, name)
            if os.path.isdir(dest):
                shutil.rmtree(dest)
            z.extractall(root)
        manifest = json.load(open(os.path.join(dest, "manifest.json"), encoding="utf-8"))
        bad = [f for f, h in manifest["files"].items() if _sha256(os.path.join(dest, f)) != h]
        if bad:
            shutil.rmtree(dest)
            raise ServerError(f"data package is damaged (hash mismatch: {', '.join(bad)}); download it again")
    finally:
        if tmp:
            os.remove(tmp)
    log(f"installed {manifest['n_articles']:,} articles to {dest}")
    return dest


MODEL_IGNORE = ["onnx/*", "*.onnx", "*.onnx_data", "imgs/*", "*.png", "*.jpg"]  # files offline mode never reads


def model_dir(model=MODEL, download=True, log=print, progress=None):
    """Local folder of the embedding model: the folder itself, the Hugging Face cache, or a fresh download (2.3 GB)."""
    def complete(path):
        p = Path(path)
        return (p / 'config.json').is_file() and (p / 'tokenizer_config.json').is_file() and any(
            (p / name).is_file() for name in ('model.safetensors', 'pytorch_model.bin', 'model.safetensors.index.json'))
    if os.path.isdir(model):
        if not complete(model):
            raise ServerError('Local search files are incomplete. Restore the complete model folder.')
        return model
    from huggingface_hub import snapshot_download
    try:
        path = snapshot_download(model, local_files_only=True, ignore_patterns=MODEL_IGNORE)
        if not complete(path):
            raise ServerError('Local search files are incomplete.')
        return path
    except Exception:  # noqa: BLE001 (not cached yet)
        if not download:
            raise
    log(f"downloading the embedding model {model} (about 2.3 GB, once) ...")
    kwargs = {}
    if progress:
        from tqdm.auto import tqdm
        class Progress(tqdm):
            def __init__(self, *args, **kw):
                kw['disable'] = False
                super().__init__(*args, **kw)
            def display(self, *args, **kw):
                progress(self.n, self.total, 'bytes' if self.unit == 'B' else 'files')
        kwargs['tqdm_class'] = Progress
    path = snapshot_download(model, ignore_patterns=MODEL_IGNORE, **kwargs)
    if not complete(path):
        raise ServerError('Local search files are incomplete.')
    log("model ready")
    return path


def prefetch_model(model=MODEL, log=print):
    """Download the embedding model once so the first search does not wait for it."""
    model_dir(model, log=log)


# Progress bars write to stderr, which some agents (Codex CLI's sandbox) give MCP servers in an unusable state.
os.environ.setdefault("TQDM_DISABLE", "1")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def _load_encoder(cls, model, device):
    """Load from a local folder, so starting the tools needs no network once the model is cached."""
    return cls(model, device)


class LocalClient:
    """Local tool client. The index loads in a background thread; the encoder loads on the first text query."""

    def __init__(self, db=None, model=MODEL, device=None, encoder=None):
        self.db = find_db(db)
        self.server = f"local data package {self.db}"
        self._index, self._error = None, None
        self._ready = threading.Event()

        def load():
            try:
                from .server.index import BGEM3Encoder, Index
                enc = encoder or _load_encoder(BGEM3Encoder, model, device)
                self._index = Index(self.db, enc)
            except Exception as e:  # noqa: BLE001 (reported on the next call)
                self._error = f"{type(e).__name__}: {e}"
            finally:
                self._ready.set()
        threading.Thread(target=load, daemon=True).start()

    def index(self, timeout=900):
        if not self._ready.wait(timeout):
            raise ServerError("the local index is still loading; try again in a minute")
        if self._error:
            raise ServerError(f"the local index could not be loaded: {self._error}")
        return self._index

    def _run(self, fn, **kw):
        from .server.index import QueryError
        try:
            return fn(**kw)
        except QueryError as e:
            raise ServerError(str(e)) from e

    def health(self):
        return {"ok": True, "mode": "local", **self.index().info()}

    def similar(self, **kw):
        idx = self.index()
        return self._run(idx.similar, **{k: v for k, v in kw.items() if v is not None})

    def article(self, doi):
        idx = self.index()
        return self._run(idx.article, doi=doi)
