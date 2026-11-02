# 0.3.0 — first-use setup and recovery

- Guided launcher installs appropriate search components, checks usability, protects against simultaneous setup, and reuses completed installations. Requires 64-bit Python 3.11–3.13.
- First-use search preparation has download progress, elapsed time and retry. Manuscript preview and settings remain usable while preparing.
- Connection tests require a valid model reply. Empty responses, invalid keys, unsupported model names and allowance errors offer useful next steps.
- Subscription setup links to official CLI installation and login instructions, with separate installation/login detection and connection testing.
- API setup can load model IDs without generating text. Custom API addresses are visible directly in the form.
- Model operations support cancellation and retry while preserving inputs. Startup reuses a matching running app and selects another address if needed.

The interface continues to hide embedding model and device settings. Article vectors and scoring rules are unchanged. There is no hosted product path.

Acceptance checks used a fresh Windows environment and an empty search-file cache. Actual retrieval used the installed encoder and bundled index; provider requests used a local test service, without paid calls. macOS/Linux and live subscription/API generation were not exercised in this acceptance run.
