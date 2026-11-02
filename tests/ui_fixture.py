"""Explicit browser-QA helper: fake LLM, real index. Never used by the application launcher.

Run with local database and encoder directories as positional arguments. No paid model calls.
"""
import sys
import uvicorn
from model_fixture import fake_model
from nearest_prior_work.server.index import BGEM3Encoder, Index
from nearest_prior_work.server.web import build_local_app

if __name__ == "__main__":
    idx = Index(sys.argv[1], BGEM3Encoder(sys.argv[2]))
    app = build_local_app(idx, model_transport=fake_model([]))
    uvicorn.run(app, host="127.0.0.1", port=8802, log_level="warning")
