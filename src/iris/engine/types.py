"""
Data type dataclasses for the IRIS pipeline engine.

All typed data flowing through the pipeline is one of these dataclasses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np


@dataclass
class PipelineContext:
    """Immutable context for a pipeline run."""
    paths: Dict[str, str]
    window_ms: Tuple[float, float]
    mea_fs_hz: float = 20000.0
    rtsort_fs_hz: float = 20000.0
    output_dir: Optional[str] = None
    cache_dir: Optional[str] = None
    verbose: bool = True
    ops_cfg: Dict[str, Dict] = field(default_factory=dict)
    current_expr: Optional[Any] = None  # ExprNode, but avoid circular import
    show_ops_params: bool = False
    interactive_plots: bool = False
    memory_cache: bool = True
    disk_cache: bool = True
    save_plots: bool = False
    plot_backend: Optional[str] = None
    cache: Optional[Any] = None

    @property
    def window_samples_mea(self) -> Tuple[int, int]:
        s, e = self.window_ms
        fs = self.mea_fs_hz
        return (int(s * fs / 1000), int(e * fs / 1000))

    @property
    def window_samples_rtsort(self) -> Tuple[int, int]:
        s, e = self.window_ms
        fs = self.rtsort_fs_hz
        return (int(s * fs / 1000), int(e * fs / 1000))


@dataclass
class MEATrace:
    """Single-channel MEA voltage trace (raw or filtered)."""
    data: np.ndarray
    fs_hz: float
    channel_idx: int
    window_samples: Tuple[int, int]
    margin_left: int = 0
    margin_right: int = 0
    label: str = ""

    @property
    def trimmed_data(self) -> np.ndarray:
        if self.margin_left == 0 and self.margin_right == 0:
            return self.data
        end = len(self.data) - self.margin_right if self.margin_right > 0 else len(self.data)
        return self.data[self.margin_left:end]


@dataclass
class MEABank:
    """Collection of MEA traces (all channels)."""
    traces: np.ndarray          # (n_channels, n_samples)
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray       # (n_channels, 2)
    window_samples: Tuple[int, int]
    margin_left: int = 0
    margin_right: int = 0
    label: str = ""


@dataclass
class CATrace:
    """Calcium imaging trace (single ROI), interpolated to MEA grid."""
    data: np.ndarray
    fs_hz: float
    trace_idx: int
    window_samples: Tuple[int, int]
    original_data: Optional[np.ndarray] = None
    original_frames: Optional[np.ndarray] = None
    baseline: Optional[np.ndarray] = None
    label: str = ""


@dataclass
class RTTrace:
    """RTSort model output trace (single channel)."""
    data: np.ndarray
    fs_hz: float
    channel_idx: int
    window_samples: Tuple[int, int]
    label: str = ""


@dataclass
class RTBank:
    """Collection of RTSort model output traces (all channels)."""
    traces: np.ndarray          # (n_channels, n_samples) — logits
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray       # (n_channels, 2)
    window_samples: Tuple[int, int]
    label: str = ""


@dataclass
class SpikeTrain:
    """Result of spike detection or RT thresholding."""
    spike_indices: np.ndarray
    spike_values: np.ndarray
    threshold_curve: np.ndarray
    source_signal: np.ndarray
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    num_spikes: int = 0
    label: str = ""

    def __post_init__(self):
        self.num_spikes = len(self.spike_indices)


@dataclass
class SimCalcium:
    """Simulated calcium trace from spike train convolution."""
    data: np.ndarray
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    spike_indices: np.ndarray = field(default_factory=lambda: np.array([], dtype=int))
    label: str = ""


@dataclass
class SimCalciumBank:
    """Collection of SimCalcium traces (one per MEA channel)."""
    traces: np.ndarray          # (n_channels, n_samples)
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray
    electrode_info: List[Dict]
    window_samples: Tuple[int, int]
    label: str = ""


@dataclass
class CorrelationResult:
    """Result of x_corr operation."""
    correlations: np.ndarray
    best_idx: int
    best_corr: float
    electrode_info: List[Dict]
    ca_trace_idx: int
    x_coords: np.ndarray
    y_coords: np.ndarray
    ca_signal: np.ndarray
    best_sim_trace: np.ndarray
    window_samples: Tuple[int, int]
    fs_hz: float
    label: str = ""
    pct_masked: Optional[np.ndarray] = None  # (n_channels,) % saturation per electrode, or None


@dataclass
class _SpikeBankIntermediate:
    """Internal: collection of SpikeTrain results, one per MEA channel."""
    spike_trains: List[SpikeTrain]
    fs_hz: float
    channel_ids: np.ndarray
    locations: np.ndarray
    window_samples: Tuple[int, int]


@dataclass
class SpikePCA:
    """PCA projection of spike waveforms with outlier flagging."""
    spike_indices: np.ndarray           # (n_spikes,) sample indices of valid spikes
    spike_values: np.ndarray            # (n_spikes,) amplitude at each spike
    waveforms: np.ndarray               # (n_spikes, snippet_len) voltage snippets
    pca_projections: np.ndarray         # (n_spikes, n_components) PC scores
    pca_components: np.ndarray          # (n_components, snippet_len) principal axes
    explained_variance_ratio: np.ndarray  # (n_components,) variance fraction per PC
    centroid: np.ndarray                # (n_components,) mean PC-space location
    distances: np.ndarray               # (n_spikes,) Euclidean distance from centroid
    outlier_mask: np.ndarray            # (n_spikes,) bool — True = flagged outlier
    source_signal: np.ndarray           # pass-through for spike_curate → gcamp_sim
    threshold_curve: np.ndarray         # pass-through for spike_curate
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    n_outliers: int = 0
    label: str = "spike_pca"

    def __post_init__(self):
        self.n_outliers = int(np.sum(self.outlier_mask))


@dataclass
class Spectrogram:
    """Time-frequency representation from scipy.signal.spectrogram."""
    frequencies: np.ndarray       # Frequency bins (Hz)
    times: np.ndarray            # Time bins (ms)
    power: np.ndarray            # Power spectral density (2D: freq x time)
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    label: str = "spectrogram"


@dataclass
class FreqPowerTraces:
    """Power vs time extracted at specific frequencies from a Spectrogram."""
    times: np.ndarray                      # Time bins (ms), shape (T,)
    freq_traces: Dict[float, np.ndarray]   # {actual_hz: power_vs_time}
    broadband_power: np.ndarray            # Mean power over broadband range, shape (T,)
    broadband_range_hz: Tuple[float, float]
    fs_hz: float
    source_id: Union[int, str]
    window_samples: Tuple[int, int]
    label: str = "freq_traces"


@dataclass
class SaturationReport:
    """Per-channel saturation episode summary for all MEA channels."""
    channel_ids: np.ndarray
    locations: np.ndarray
    samples_masked: np.ndarray   # (n_channels,) masked sample count per channel
    total_samples: int
    window_samples: Tuple[int, int]
    fs_hz: float
    label: str = "saturation_survey"
    plot_type: str = "histogram"  # "histogram", "scatter", or "survival"
