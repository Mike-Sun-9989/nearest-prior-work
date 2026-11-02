# 0.3.5 — Clearer model setup

- Checking for an installed CLI no longer fails on Windows systems whose default text encoding is not UTF-8. The check previously stopped with an internal error message instead of reporting the CLI.
- Unexpected internal errors no longer show their raw text on the page.
- Model settings now show a **Setup guide** with only the steps still needed. It collapses when the selected CLI is installed and signed in.
- The page checks again when you return to it, and **Check again now** does the same on request. The first time settings open, a signed-in CLI is selected if the default is not ready.
- Cancelling a model request right after it starts now stops the worker at once and no longer reports it as still running. This removes an occasional test failure on Macs.
- The bundled index, retrieval and scoring are unchanged.
