"""One shared, retryable download per app; contains no manuscript or provider credentials."""
import threading
import time


class SearchPreparation:
    def __init__(self, encoder):
        self.encoder = encoder
        self.lock = threading.Lock()
        self.state = 'needed'
        self.done = self.total = 0
        self.unit = 'files'
        self.message = ''
        self.started = None
        if not hasattr(encoder, 'model_name'):
            self.state = 'ready'
        else:
            from ..local import model_dir
            try:
                model_dir(encoder.model_name, download=False, log=lambda *_: None)
                self.state = 'ready'
            except Exception:
                pass

    def status(self):
        with self.lock:
            return {'state': self.state, 'files_done': self.done, 'files_total': self.total,
                    'unit': self.unit,
                    'seconds': round(time.monotonic()-self.started) if self.started else 0,
                    'message': self.message, 'download_size': 'about 2.3 GB'}

    def start(self):
        with self.lock:
            if self.state in ('preparing', 'ready'):
                return
            self.state, self.message = 'preparing', ''
            self.done = self.total = 0
            self.unit = 'files'
            self.started = time.monotonic()
        def progress(n, total, unit='files'):
            with self.lock:
                self.done, self.total, self.unit = n, total or 0, unit
        def run():
            from ..local import model_dir
            try:
                model_dir(self.encoder.model_name, progress=progress, log=lambda *_: None)
                with self.lock:
                    self.state = 'ready'
            except Exception:
                with self.lock:
                    self.state = 'error'
                    self.message = ('Search files could not be prepared. Check your internet connection and free disk space, '
                                    'then choose Retry preparation. Completed downloads will be reused.')
        threading.Thread(target=run, daemon=True).start()

    def failed(self):
        with self.lock:
            self.state = 'error'
            self.message = 'Local search could not start. Retry preparation. If this continues, rerun the launcher to repair the installation.'
