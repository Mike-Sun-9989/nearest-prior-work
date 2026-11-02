# Platform requirements and verification

| System | Supported configuration |
|---|---|
| Windows | Windows 10 or 11 on x64 computers; CPU-only or a compatible NVIDIA GPU |
| macOS | Apple silicon, macOS 14 or later |

GPU acceleration is optional. The app automatically tries an available accelerator and retries on CPU if model loading or encoding fails. Search uses one text chunk per batch to limit peak memory. The chunk boundaries, overlap, averaging and ranking definition are unchanged. Long manuscripts on a CPU can take minutes; elapsed time stays visible. 16 GB RAM is recommended for comfortable use, not a guarantee about every document or machine. No minimum-memory hardware acceptance has been performed.

The Windows installer selects CPU components when no NVIDIA GPU is detected. Apple silicon (M-series) Macs use MPS when available. No GPU is required on either supported system.

About 15 GB free is a comfortable setup allowance. The preflight floor is lower for CPU/Apple silicon installs (8 GB on the app drive, with separate temporary/cache checks), so those installs are not blocked by a CUDA-sized disk estimate. Download caches and existing files can still increase actual use.

Intel Macs, Python under Rosetta, Windows on ARM, 32-bit systems and all Linux distributions are outside this release's supported configuration. The installer explains an unsupported platform before creating the app environment or downloading large dependencies. The macOS requirement follows [Apple's PyTorch guidance](https://developer.apple.com/metal/pytorch/).

On Windows, double-click `start.bat`. On a Mac, double-click `start.command` or run `bash start.sh` from the extracted folder as your normal user. The launcher uses an installed 64-bit Python 3.11–3.13 (native arm64 on a Mac) when one exists. Otherwise it downloads a pinned, checksum-verified standalone CPython 3.13 into `.runtime`. It can repair an incomplete environment on retry. The app only listens on the local computer.

## Reproduce a CPU check

For troubleshooting or acceptance testing, use `python setup_local.py --cpu --install-only` to create a CPU environment. Continue using `--cpu` when launching that environment. Regular users can continue using the normal launcher with automatic selection.

Run the environment's Python with `tools/smoke_local.py --device cpu --prepare`. The optional `--prepare` permits downloading the search files; omit it to require an existing cache. This checks actual localhost startup, DOI retrieval, cold text retrieval, the six-section synthetic manuscript, multi-chunk retrieval and blocked-network retrieval. It makes no LLM calls. Timings describe the machine used, not every CPU.

CI covers Windows and Apple silicon macOS with Python 3.11–3.13, using CPU installation. Its manual `real_search` option additionally runs this real-model check on Python 3.12; normal CI uses synthetic vectors and mock providers. A configured CI job is not a completed run. Hosted Windows runners use Windows Server, so passing CI does not establish Windows 10/11 desktop acceptance.

Actual local installation and retrieval have been checked on Windows 11 and an M-series Mac, including CPU operation. Windows 10 is a compatibility target; its version gate is tested, but a Windows 10 machine has not yet been used for full first-install and retrieval acceptance. These results do not establish performance on low-memory computers. Mac CLI detection and mocked providers have been checked; a real signed-in Codex CLI connection has only been exercised on Windows.
