"""Tüm testler için ortak ayar: hypothesis deterministik ve koşudan koşuya veri taşımaz."""

import atexit
import shutil
import tempfile

from hypothesis import settings
from hypothesis.configuration import set_hypothesis_home_dir

# derandomize: same examples every run (docs/testing.md, Determinism);
# database=None: no example database carried between runs (Resource hygiene rule 5)
settings.register_profile("crytobot", derandomize=True, database=None)
settings.load_profile("crytobot")

# Hypothesis still caches unicode tables and collected constants in its home directory; a fresh
# directory per run, removed at exit, keeps .hypothesis/ out of the tree (Resource hygiene rule 5).
_home = tempfile.mkdtemp(prefix="crytobot-hypothesis-")
set_hypothesis_home_dir(_home)
atexit.register(shutil.rmtree, _home, ignore_errors=True)
