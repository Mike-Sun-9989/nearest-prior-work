# Local application, version 0.2

The product has one deployment mode: a browser interface served on the user's computer, with the article index included in the repository and package. The hosted service, application keys and remote client have been removed. Language model calls use the user's configured CLI subscription, API key or local endpoint.

The manuscript workflow now separates local file inspection, explicit model identification, editable section review and retrieval. The interface hides the embedding model and device selection; BGE-M3 remains the local encoder, choosing CUDA, then MPS, then CPU. DOI searches do not initialize it. Windows and Unix startup scripts create a virtual environment and start the local app.

Section-specific retrieval now searches the entire eligible index. Result positions, exports and copied DOIs follow the current ranking. Details preserve the original whole-index section ranks and show coverage; the research rule for overall scores is unchanged. A transient query-vector cache avoids encoding the same text again when filters or ranking change.

Verification includes unit/integration tests with synthetic vectors and mocked model providers, a browser walkthrough using the bundled 10,357-article index and the local model, and a wheel/data/export audit. The browser walkthrough covered file inspection, model settings, section editing, real retrieval, DOI retrieval, section ranking, details and CSV export. Mocked identification tests do not establish live-provider availability. No paid calls or research experiments were rerun. Clean-machine installation and other operating systems still require release testing.
