# Bundled index and third-party materials

The project's original code, documentation, synthetic examples and original contributions to the bundled index are offered under the [MIT License](LICENSE). The copyright notice uses the project contributor name for the anonymous review distribution.

The index contains metadata and section vectors for 10,357 articles in seven management journals, covering 1996–2026. It contains article identifiers, titles, journals, years, section vectors and reference distributions. It contains no article abstracts, full text, PDFs or chunk-level vectors. The original articles remain the work of their respective authors and publishers; the project's license does not grant rights to those underlying works or change any third-party terms.

The index is the v2 research output described in [the data format](docs/server_db_format.md). Numerical files and article metadata are unchanged by application packaging. Checksums in `src/nearest_prior_work/data/manifest.json` describe the shipped files. Packaging updates to the accompanying README do not change the research sample or scores.

The encoding model is downloaded separately from [BAAI/bge-m3](https://huggingface.co/BAAI/bge-m3); its files and license are supplied by that model's publisher. When no suitable Python is installed, the launcher downloads CPython from [python-build-standalone](https://github.com/astral-sh/python-build-standalone) under its own licenses. Python libraries, model services and command-line agents retain their own licenses and service terms. Credentials and user manuscripts are not part of this repository.
