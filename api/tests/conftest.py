import os
import sys

# Make the api/ directory importable (app.main, app.report).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


import pytest


@pytest.fixture(autouse=True)
def _fresh_cache():
    """Le cache d'agrégat bâtiment est keyé par id : sans purge, un test
    servirait la fixture du précédent (mêmes ids partout)."""
    from app import main
    main._CACHE.clear()
    yield
    main._CACHE.clear()
