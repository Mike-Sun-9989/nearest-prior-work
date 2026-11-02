# Local database format

The application reads its bundled database from `nearest_prior_work/data`. Row i in each file refers to the same article.

| File | Content |
|---|---|
| articles.parquet | row (0..n-1), doi (nullable), title, journal, journal_code, year (nullable) |
| vectors_SECTION.npy | float16 matrix (n, 1024); a normalized section vector or an all-NaN row for an absent section |
| random_pairs.npz | reference cosine distributions used for section z scores and percentiles |
| manifest.json | index name, coverage, encoder specification and file checksums |

The bundled v2 index has no abstracts or article text. It is copied without changing metadata or vectors. See [local application details](local_app.md) for query encoding and ranking definitions.
