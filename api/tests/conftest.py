import os
import sys

# Make the api/ directory importable (app.main, app.report).
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
