A test-only extension, installed by putting this folder on `sys.path`: the `.dist-info`
folder makes `importlib.metadata` find its entry point as it would for a real package.
Used by `tests/test_ext_e2e.py`. It uses only the host API (CLAUDE.md §15).
