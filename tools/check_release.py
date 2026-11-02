"""Verify the distributable tree and optional wheel. No network or model calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {'.gitignore', '.gitattributes', 'README.md', 'LICENSE', 'DATA_NOTICE.md',
              'CONTRIBUTING.md', 'pyproject.toml', 'constraints.txt', 'setup_local.py', 'start.bat', 'start.sh', 'start.command'}
DIRECTORIES = {'src', 'docs', 'examples', 'tests', 'tools', '.github'}
EXCLUDED = {'__pycache__', '.pytest_cache', 'build', 'dist', '.git'}
TEXT_EXTENSIONS = {'.py', '.md', '.txt', '.toml', '.yml', '.yaml', '.html', '.js', '.sh', '.command', '.bat', '.json'}


def release_files():
    files = []
    for p in ROOT.rglob('*'):
        rel = p.relative_to(ROOT)
        if rel.parts[0] not in ROOT_FILES | DIRECTORIES: continue
        if any(part in EXCLUDED or part.endswith('.egg-info') for part in rel.parts): continue
        if p.is_symlink(): raise ValueError(f'Symlink is not a release file: {rel}')
        if p.is_file() and p.suffix != '.pyc': files.append(p)
    return sorted(files)


def check_tree():
    files = release_files()
    assert ROOT_FILES <= {p.name for p in files if p.parent == ROOT}, 'Missing top-level release file'
    secrets = re.compile(r'(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{25,}|AKIA[A-Z0-9]{16}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    personal = re.compile(r'(?:[A-Za-z]:[\\/](?:Users|network_papers)[\\/]|[/]Users[/][^/\s]+/|[/]home[/][^/\s]+/)')
    blocked = re.compile(r'(?i)(?:^\.env(?:\.|$)|api[_-]?key|credentials|^auth\.json$|\.log$|\.(?:key|pem)$)')
    for p in files:
        rel = p.relative_to(ROOT)
        assert not blocked.search(p.name), f'Private filename in release: {rel}'
        assert not any(x in {'.codex', '.claude', '.idea', '.vscode'} or x.startswith('.venv') for x in rel.parts), rel
        assert p.stat().st_size < 50 * 2**20, f'Unexpected large file: {rel}'
        if p.suffix in TEXT_EXTENSIONS or p.name in ROOT_FILES:
            text = p.read_text(encoding='utf-8-sig')
            for n, line in enumerate(text.splitlines(), 1):
                assert not secrets.search(line), f'Possible credential: {rel}:{n} (value withheld)'
                assert not personal.search(line), f'Personal absolute path: {rel}:{n}'
            if p.suffix == '.md':
                for link in re.findall(r'\]\(([^)]+)\)', text):
                    if re.match(r'^[a-z]+://|^#', link): continue
                    target = (p.parent / link.split('#')[0]).resolve()
                    assert target.is_relative_to(ROOT) and target.exists(), f'Broken local link: {rel}: {link}'
        if p.suffix in {'.sh', '.command'}: assert b'\r' not in p.read_bytes(), f'Shell script needs LF: {rel}'
        if p.suffix == '.png': assert p.read_bytes().startswith(b'\x89PNG'), f'Wrong PNG signature: {rel}'
        if p.suffix == '.jpg': assert p.read_bytes().startswith(b'\xff\xd8'), f'Wrong JPEG signature: {rel}'
    assert 'MIT License' in (ROOT/'LICENSE').read_text()
    print(f'Release files: {len(files)}; largest: {max(p.stat().st_size for p in files)/2**20:.2f} MiB')
    print('PASS: local documentation links, common secret/path patterns, line endings and image signatures.')
    return files


def check_data():
    import numpy as np
    import pandas as pd
    data = ROOT/'src/nearest_prior_work/data'
    manifest = json.loads((data/'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((data/name).read_bytes()).hexdigest() == digest, name
    articles = pd.read_parquet(data/'articles.parquet')
    n = manifest['n_articles']
    assert list(articles.columns) == ['row', 'doi', 'title', 'journal', 'journal_code', 'year']
    assert len(articles) == n == 10357 and articles.row.is_unique
    assert np.array_equal(articles.row.to_numpy(), np.arange(n))
    assert articles.doi.dropna().is_unique and articles.year.dropna().between(1996, 2026).all()
    for section in manifest['sections']:
        vectors = np.load(data/f'vectors_{section}.npy', mmap_mode='r')
        assert vectors.shape == (n, 1024) and vectors.dtype == np.float16
        valid = np.isfinite(vectors).all(axis=1)
        assert valid.sum() == manifest['articles_with_section'][section]
        assert np.isnan(vectors[~valid]).all()
        norms = np.linalg.norm(vectors[valid].astype(np.float32), axis=1)
        assert np.allclose(norms, 1, atol=.002), section
    print(f'Input/output article rows: {n}/{n}; columns: {list(articles.columns)}')
    print('Year describe:', articles.year.describe().to_dict())
    print(f'Missing DOI/year: {articles.doi.isna().sum()}/{articles.year.isna().sum()}')
    print('Dropped rows: 0; merges: none; unmatched samples: not applicable.')
    print('PASS: bundled checksums, schema, unique keys, ranges and nine normalized vector matrices.')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wheel', type=Path)
    args = ap.parse_args()
    files = check_tree()
    check_data()
    if args.wheel:
        with zipfile.ZipFile(args.wheel) as z:
            expected = {p.relative_to(ROOT/'src').as_posix(): p for p in files if p.is_relative_to(ROOT/'src')}
            for name, p in expected.items(): assert z.read(name) == p.read_bytes(), name
            assert not any('auth.json' in n or '.env' in n or n.endswith(('.pdf', '.docx')) for n in z.namelist())
            assert any(n.endswith('/licenses/LICENSE') for n in z.namelist()), 'MIT license absent from wheel'
        print(f'PASS: wheel contains {len(expected)} matching package files and the MIT license.')


if __name__ == '__main__': main()
