"""Run offline checks with temporary files confined to this checkout."""
from pathlib import Path
import sys
import tempfile
import unittest

root = Path(__file__).resolve().parents[1]
scratch = (root / '.state' / 'test-tmp').resolve()
if not scratch.is_relative_to(root):
    raise SystemExit('Test directory must remain inside the checkout')
scratch.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(scratch)
sys.path.insert(0, str(root))
suite = unittest.defaultTestLoader.discover(str(root / 'tests'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
