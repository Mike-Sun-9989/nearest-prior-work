# 0.3.1 — repository distribution

- MIT license and explicit index/third-party scope; anonymous contributor attribution retained.
- Expanded ignore rules for credentials, user configuration, backup environments and logs. Shell and batch line endings are fixed for Git checkouts.
- Old screenshots replaced with current local-app views. Quickstart and troubleshooting cover installation through first model-assisted search.
- Unsupported default Python versions trigger discovery of a supported installed interpreter. Space checks cover environment, temporary and search-cache locations. Shared developer environments receive an explicit clean-install instruction.
- Model connection/test/cancel actions remain visible at the bottom of the settings dialog.
- Repository/wheel checks and a cross-platform Python test workflow are included. CI makes no real model calls and does not publish.
- Missing DOI values are serialized as JSON null across pandas versions, including pandas 3; articles remain in the index and search results.

Article metadata, vectors, reference distributions and scoring rules are unchanged. The data README and its manifest checksum now describe the shipped workflow.
