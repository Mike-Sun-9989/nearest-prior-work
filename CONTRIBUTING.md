# Development and release checks

Keep this repository focused on the distributable local app. Do not add research workspaces, original PDFs, full-text corpora, provider keys, agent authentication, virtual environments or local logs. The approved article metadata and numerical index belong in `src/nearest_prior_work/data/`; they are explicit exceptions in `.gitignore`.

## Layout

- `start.bat`, `start.sh`, `start.command`, `setup_local.py`: first installation and local launch. The Python version and checksum pinned in `start.bat` and `start.sh` must stay in step.
- `src/nearest_prior_work/`: local search, document processing, model adapters and browser app.
- `src/nearest_prior_work/data/`: bundled metadata, vectors and checksums.
- `docs/`: quickstart, troubleshooting, technical notes and current screenshots.
- `examples/`: synthetic manuscript and its reproducible Word generator.
- `tests/`: automated checks and explicit mock providers; no production credentials.
- `tools/check_release.py`: repository and wheel checks, without model calls.
- `.github/workflows/test.yml`: Windows and Apple silicon macOS / Python test matrix; never publishes.

## Validate a change

Create an independent environment with the launcher. Use its Python to install `-c constraints.txt -e ".[test]"`, run `-m pytest -q`, then `tools/check_release.py`. A developer environment that shares global site packages is not a clean-install acceptance environment.

Before distribution, build with `python -m pip wheel . --no-deps -w dist`, then run `python tools/check_release.py --wheel dist/nearest_prior_work-0.3.6-py3-none-any.whl` using the environment's Python. When committing from Windows, run `git add --chmod=+x start.command start.sh`; without the executable bit a Mac cannot double-click `start.command`. Review the actual file list, not just `.gitignore`. Scan the export for credentials, personal paths and private notes.

## First-use acceptance

Export only the intended repository files into a ZIP. Extract it to a new folder, including a path with spaces. Run the launchers without copying `.venv` or app settings. Use a separate empty `HF_HOME` cache to exercise first preparation. Confirm the installed package is loaded from this extracted copy.

Test installation, local page startup, preparation and retry, then configure an installed/signed-in Codex CLI from the page. Test the connection and identify `examples/demo_manuscript.docx`; review roles, search, change ranking and export. A real provider check uses a small allowance and belongs in a deliberate manual acceptance run, never routine CI. Compare the exported rows with the displayed order. Also exercise missing-CLI and invalid-key cases without changing real account credentials.

Record which operating systems, Python versions and devices were actually used. Retain acceptance logs outside the release folder. Keep the underlying index, sample rules and similarity definition unchanged unless a separately reviewed research change requires them.
