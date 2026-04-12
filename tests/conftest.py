"""Shared pytest fixtures for the CASI test suite."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make `casi` importable without installing the package — works for both
# `uv run pytest` (which installs in dev mode) and `python -m pytest` from
# a fresh checkout.
SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_configs_dir(tmp_path: Path) -> Path:
    """Build a minimal valid configs/ tree inside a tmp dir.

    Used by the CLI tests so they don't depend on the real configs/ files
    in the repo.
    """
    cfg = tmp_path / "configs"
    cfg.mkdir()

    (cfg / "paths.yaml").write_text(
        """
mea_h5: nonexistent_mea.h5
ca_traces_npz: nonexistent_ca.npz
output_dir: outputs
cache_dir: cache
""".strip()
    )

    (cfg / "ops.yaml").write_text(
        """
butter_bandpass:
  low_hz: 350
  high_hz: 6000
  order: 10
  zero_phase: true
notch_filter:
  notch_freq_hz: 60.0
  notch_q: 30.0
  harmonics: [1, 2, 3]
""".strip()
    )

    (cfg / "globals.yaml").write_text(
        """
plot_backend: matplotlib
show_ops_params: true
save_plots: false
memory_cache: true
disk_cache: false
""".strip()
    )

    # Make a fake project root with a pyproject.toml so find_project_root works
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")

    return cfg
