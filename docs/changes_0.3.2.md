# 0.3.2 — CPU and platform compatibility

- Installation checks architecture and OS compatibility before large downloads, with clear unsupported-platform messages.
- macOS/Linux environments use native symlinks so standalone Python distributions retain their standard-library location. Incomplete Linux environments can retry pip setup; missing venv support has a specific recovery instruction.
- Model loading/encoding can fall back from CUDA or MPS to CPU. Invalid accelerator output also retries once on CPU.
- One chunk per encoding batch limits memory use; CPU thread count is bounded. Chunk boundaries, averaging, index data and scoring remain unchanged.
- Search displays elapsed time and explains the longer first/manuscript search.
- CPU memory exhaustion suggests closing other apps or using a shorter section, without asking users to download the model again.
- CPU installation is available for troubleshooting and CI. A portable real-search smoke tool checks startup, DOI/text/manuscript retrieval and offline operation without calling a language model.
