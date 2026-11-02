# 0.3.4 — Start without installing Python

- `start.bat` and `start.sh` use an installed Python 3.11–3.13 when one exists. Otherwise they download a pinned CPython 3.13 into `.runtime`, verify its SHA-256 and continue. Users no longer choose a Python version or change installer options.
- The launchers run a real version check, so a Windows `python` shortcut that does not run Python, or macOS's older `/usr/bin/python3`, no longer stops setup. The Python install manager is not allowed to download a runtime during this check.
- New `start.command` lets Mac users start by double-clicking. macOS may ask for approval because the file is not notarized.
- The search files start downloading the first time the page opens. A failed download still shows **Retry preparation** and is not retried automatically.
- The DOI page states that the collection does not contain every article from its journals and lists articles and years per journal. A DOI that is not found now explains why and offers **Paste a section instead**.
- The bundled index, retrieval and scoring are unchanged.
