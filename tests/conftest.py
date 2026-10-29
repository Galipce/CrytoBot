"""Tüm testler için ortak ayar: hypothesis deterministik ve koşudan koşuya veri taşımaz."""

from hypothesis import settings

# derandomize: same examples every run (docs/testing.md, Determinism);
# database=None: no .hypothesis/ directory left behind (Resource hygiene rule 5)
settings.register_profile("crytobot", derandomize=True, database=None)
settings.load_profile("crytobot")
