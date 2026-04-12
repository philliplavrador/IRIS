"""Saturation op handlers: saturation_mask, saturation_survey."""
from __future__ import annotations

import numpy as np
from tqdm.auto import tqdm

from iris.engine.types import MEABank, MEATrace, PipelineContext, SaturationReport


def op_saturation_mask(inp, ctx: PipelineContext, *,
                       min_run=20, eps_range=1.0,
                       lookahead=400, recovery_eps=5.0,
                       pre_samples=0, mode="fill_nan", scope="all",
                       sync_cut=False, drop_saturated_pct=None):
    # --- MEABank branch: bank-level operations (sync_cut / drop_saturated_pct) ---
    if isinstance(inp, MEABank):
        n_channels = inp.traces.shape[0]
        ml, mr = inp.margin_left, inp.margin_right
        total_samples = inp.traces.shape[1] - ml - (mr if mr > 0 else 0)
        min_run_i = int(min_run)
        lookahead_i = int(lookahead)

        lead_end = np.zeros(n_channels, dtype=np.int64)
        for ch_i in tqdm(range(n_channels), desc="  saturation_mask", leave=False):
            raw = inp.traces[ch_i]
            end = len(raw) - mr if mr > 0 else len(raw)
            signal = raw[ml:end]
            n = len(signal)
            i = 0
            while i <= n - min_run_i:
                ref_val = signal[i]
                run_len = 1
                for j in range(i + 1, min(i + min_run_i, n)):
                    if abs(signal[j] - ref_val) <= eps_range:
                        run_len += 1
                    else:
                        break
                if run_len < min_run_i:
                    i += 1
                    continue
                sat_start = i
                sat_end = i + min_run_i
                while sat_end < n and abs(signal[sat_end] - ref_val) <= eps_range:
                    sat_end += 1
                end_val = signal[sat_end - 1]
                while sat_end < n:
                    window_end = min(sat_end + lookahead_i, n)
                    chunk = signal[sat_end:window_end]
                    hits = np.where(np.abs(chunk - end_val) <= recovery_eps)[0]
                    if len(hits) == 0:
                        break
                    sat_end = sat_end + hits[-1] + 1
                    end_val = signal[sat_end - 1]
                if sat_start == 0:
                    lead_end[ch_i] = sat_end
                break

        lead_pct = lead_end / total_samples if total_samples > 0 else np.zeros(n_channels)
        traces = inp.traces
        channel_ids = inp.channel_ids
        locations = inp.locations

        if drop_saturated_pct is not None:
            threshold = float(drop_saturated_pct)
            keep_mask = lead_pct < threshold
            n_dropped = int(np.sum(~keep_mask))
            print(f"  saturation_mask: dropping {n_dropped} channel(s) "
                  f"with leading saturation >= {threshold*100:.1f}% of window")
            traces = traces[keep_mask]
            channel_ids = channel_ids[keep_mask]
            locations = locations[keep_mask]
            lead_end = lead_end[keep_mask]

        end_idx = traces.shape[1] - mr if mr > 0 else traces.shape[1]
        if sync_cut and len(traces) > 0:
            global_trim = int(np.max(lead_end))
            data = traces[:, ml:end_idx]
            if global_trim > 0:
                data = data[:, global_trim:]
                new_ws = (inp.window_samples[0] + global_trim, inp.window_samples[1])
                print(f"  saturation_mask: sync_cut trimmed {global_trim} samples "
                      f"({global_trim / inp.fs_hz * 1000:.1f} ms) from start")
            else:
                new_ws = inp.window_samples
        else:
            data = traces[:, ml:end_idx]
            new_ws = inp.window_samples

        return MEABank(
            traces=data, fs_hz=inp.fs_hz,
            channel_ids=channel_ids, locations=locations,
            window_samples=new_ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )

    # --- MEATrace branch: single-channel masking ---
    valid_modes = ("fill_nan", "fill_zeroes", "cut_window")
    if mode not in valid_modes:
        raise ValueError(f"saturation_mask mode must be one of {valid_modes}, got '{mode}'")
    if scope not in ("all", "leading"):
        raise ValueError(f"saturation_mask scope must be 'all' or 'leading', got '{scope}'")

    ml, mr = inp.margin_left, inp.margin_right
    if ml > 0 or mr > 0:
        end = len(inp.data) - mr if mr > 0 else len(inp.data)
        signal = inp.data[ml:end].copy()
    else:
        signal = inp.data.copy()

    n = len(signal)
    min_run = int(min_run)
    lookahead = int(lookahead)
    episodes = []
    i = 0

    while i <= n - min_run:
        ref_val = signal[i]
        run_len = 1
        for j in range(i + 1, min(i + min_run, n)):
            if abs(signal[j] - ref_val) <= eps_range:
                run_len += 1
            else:
                break
        if run_len < min_run:
            i += 1
            continue

        sat_start = i
        sat_end = i + min_run
        while sat_end < n and abs(signal[sat_end] - ref_val) <= eps_range:
            sat_end += 1

        end_val = signal[sat_end - 1]
        while sat_end < n:
            window_end = min(sat_end + lookahead, n)
            chunk = signal[sat_end:window_end]
            hits = np.where(np.abs(chunk - end_val) <= recovery_eps)[0]
            if len(hits) == 0:
                break
            sat_end = sat_end + hits[-1] + 1
            end_val = signal[sat_end - 1]

        raw_start = sat_start
        sat_start = max(sat_start - int(pre_samples), 0)
        episodes.append((sat_start, sat_end))
        if scope == "leading":
            if raw_start != 0:
                episodes.pop()
            break
        i = sat_end

    # --- Mode-specific masking ---
    ws = inp.window_samples

    if mode == "fill_nan":
        for s, e in episodes:
            signal[s:e] = np.nan
        masked_pct = np.sum(np.isnan(signal)) / n * 100
        print(f"  saturation_mask: {len(episodes)} episode(s), "
              f"{masked_pct:.1f}% of samples masked")
        return MEATrace(
            data=signal, fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
            window_samples=ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )

    elif mode == "fill_zeroes":
        for s, e in episodes:
            signal[s:e] = 0.0
        zeroed_pct = sum(e - s for s, e in episodes) / n * 100
        print(f"  saturation_mask: {len(episodes)} episode(s), "
              f"{zeroed_pct:.1f}% of samples zeroed")
        return MEATrace(
            data=signal, fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
            window_samples=ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )

    else:  # cut_window
        leading = [ep for ep in episodes if ep[0] == 0]
        trailing = [ep for ep in episodes if ep[1] >= n]
        middle = [ep for ep in episodes if ep[0] != 0 and ep[1] < n]

        if middle:
            print(f"  saturation_mask (cut_window): WARNING — {len(middle)} middle "
                  f"episode(s) detected, left unmasked")

        trim_left = max((ep[1] for ep in leading), default=0)
        trim_right = min((ep[0] for ep in trailing), default=n)

        if trim_left >= trim_right:
            print(f"  saturation_mask (cut_window): entire signal is saturated")
            return MEATrace(
                data=np.array([], dtype=signal.dtype),
                fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
                window_samples=(ws[0], ws[0]),
                margin_left=0, margin_right=0, label="saturation_mask",
            )

        signal = signal[trim_left:trim_right]
        new_ws = (ws[0] + trim_left, ws[0] + trim_right)

        print(f"  saturation_mask (cut_window): {len(episodes)} episode(s), "
              f"trimmed {trim_left} from start, {n - trim_right} from end, "
              f"{len(signal)} samples remain")
        return MEATrace(
            data=signal, fs_hz=inp.fs_hz, channel_idx=inp.channel_idx,
            window_samples=new_ws, margin_left=0, margin_right=0,
            label="saturation_mask",
        )


def op_saturation_survey(inp: MEABank, ctx: PipelineContext, *,
                         min_run=20, eps_range=1.0,
                         lookahead=400, recovery_eps=5.0,
                         pre_samples=0, scope="all", plot_type="histogram") -> SaturationReport:
    if scope not in ("all", "leading"):
        raise ValueError(f"saturation_survey scope must be 'all' or 'leading', got '{scope}'")
    """Count saturated samples per MEA channel and return a per-channel report."""
    n_channels = inp.traces.shape[0]
    ml, mr = inp.margin_left, inp.margin_right
    total_samples = inp.traces.shape[1] - ml - (mr if mr > 0 else 0)
    samples_masked = np.zeros(n_channels, dtype=np.int64)
    min_run_i = int(min_run)
    lookahead_i = int(lookahead)

    for ch_i in tqdm(range(n_channels), desc="  saturation_survey", leave=False):
        raw = inp.traces[ch_i]
        end = len(raw) - mr if mr > 0 else len(raw)
        signal = raw[ml:end]
        n = len(signal)
        count = 0
        i = 0
        while i <= n - min_run_i:
            ref_val = signal[i]
            run_len = 1
            for j in range(i + 1, min(i + min_run_i, n)):
                if abs(signal[j] - ref_val) <= eps_range:
                    run_len += 1
                else:
                    break
            if run_len < min_run_i:
                i += 1
                continue
            sat_start = i
            sat_end = i + min_run_i
            while sat_end < n and abs(signal[sat_end] - ref_val) <= eps_range:
                sat_end += 1
            end_val = signal[sat_end - 1]
            while sat_end < n:
                window_end = min(sat_end + lookahead_i, n)
                chunk = signal[sat_end:window_end]
                hits = np.where(np.abs(chunk - end_val) <= recovery_eps)[0]
                if len(hits) == 0:
                    break
                sat_end = sat_end + hits[-1] + 1
                end_val = signal[sat_end - 1]
            raw_start = sat_start
            sat_start = max(raw_start - int(pre_samples), 0)
            if scope != "leading" or raw_start == 0:
                count += sat_end - sat_start
            i = sat_end
            if scope == "leading":
                break
        samples_masked[ch_i] = count

    if plot_type not in ("histogram", "scatter", "survival"):
        raise ValueError(f"plot_type must be 'histogram', 'scatter', or 'survival', got '{plot_type}'")

    return SaturationReport(
        channel_ids=inp.channel_ids,
        locations=inp.locations,
        samples_masked=samples_masked,
        total_samples=total_samples,
        window_samples=inp.window_samples,
        fs_hz=inp.fs_hz,
        plot_type=plot_type,
    )
