# Local application and index

The production entry point is `npw` (or `python -m nearest_prior_work.server`). It binds only to 127.0.0.1. There is no remote MCP endpoint, key administration, hosted search client or deployment option. A loopback host/peer check and same-origin browser check protect local model execution. `npw-mcp` uses `LocalClient` directly.

## Bundled data

`src/nearest_prior_work/data/` contains the approved v2 metadata, nine section vector files, random-pair distributions and a manifest. These files are included in editable installs and built wheels. The source research data remain outside the software repository and are read-only. The shipped README describes the current local workflow. Its packaging checksum is updated separately; article metadata and all numerical files retain their original hashes.

Run `python tools/check_release.py` from this repository to check file checksums, row counts, keys, year ranges, vector dimensions and documentation links. Pass `--wheel path/to/package.whl` to compare a built wheel. No observations are dropped or merged by packaging checks.

## Retrieval method

BGE-M3 dense embeddings have 1,024 dimensions. Query text is split into pieces of 2,046 tokens starting every 1,792 tokens, embedded and normalized, averaged, and normalized again. This preserves the existing index method. A maximum of 20 chunks per input section is used; truncation is reported. Standardized scores use the unchanged random-pair reference distributions. Overall scores still average over shared sections; no minimum section-coverage rule has been introduced.

The encoder loads lazily on the first text query. CUDA is preferred, then Apple MPS, then CPU when neither GPU backend is available. CUDA uses half precision, matching the previous implementation. DOI queries require no model loading. Small numerical differences between devices may affect ties.

Selecting `rank_by` retrieves the top K of that section across the entire eligible collection while preserving per-section details and the overall score. A section missing from the query is rejected. Result positions reflect the chosen filters and ranking; detailed section ranks retain the original whole-index denominator (source excluded). The response includes index version, ranking dimension, filters and eligible article count.

## Temporary state

Raw uploaded files are removed immediately after extraction. At most four inspected documents are retained in application memory for 30 minutes, for identification and retries; closing or replacing the file requests removal. Cleanup runs every minute. The page retains its current outline until cleared, refreshed or closed. No manuscript history is written to disk.

The index caches up to 32 query embeddings, addressed by SHA-256 hashes rather than stored source text, for reuse across filters and ranking changes. Entries expire after 15 minutes on the next query and are discarded when the process stops. Model credentials are used only for the active call. Browser storage of credentials is opt-in separately from provider/model preferences.

## Verification

The standard-library bootstrap `setup_local.py` supports 64-bit Python 3.11–3.13. It selects PyTorch 2.11 from the official CUDA 12.8 wheel index on NVIDIA Windows 10/11 x64 systems, CPU wheels otherwise, and the regular macOS build for MPS. A real tensor allocation checks CUDA usability before accepting the installation; an unavailable device falls back to CPU. `constraints.txt` bounds the application dependencies. A fingerprint stamp skips completed setup, and an OS lock prevents concurrent installers from modifying the same environment.

Search preparation is a separate shared, retryable download. Progress distinguishes byte and file counters from the download library. Model tests, model-list requests and manuscript identification run in isolated worker processes with deadlines; cancellation terminates the worker and its CLI process tree. Completed results expire after ten minutes and the page removes them after receipt. Keys and manuscript input are not stored in job status. Model tests validate both response structure and the requested acknowledgement, rather than accepting HTTP status alone.

The launcher verifies the application, version and index identity before reusing a running instance. It reserves a free loopback socket when another program occupies the requested address. This does not expose a public service.

Run `python -m pytest -q`. Coverage includes true section retrieval beyond the overall top K, DOI retrieval without encoding, cache reuse, bundled-data discovery, malformed input, local host/origin restrictions, document expiry and disposal, mocked API identification and retry, and isolated Codex/Claude command construction. Live model-provider calls are not part of automated tests.

The previous public-server authentication and rate-limit tests were retired together with that product path. No research experiments or frozen evaluation inputs are modified by application tests.
