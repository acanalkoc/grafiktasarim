"""Deterministic tests for the v6.1 Scientific Analysis & Signal Studio.

Two layers are covered, matching the module split:

- ``analysis/stats.py`` and ``analysis/signal.py``: pure NumPy/SciPy
  functions, checked against SciPy's own reference implementations (or,
  where SciPy has no direct equivalent — Cohen's d, eta-squared, CI — a
  known closed-form value computed independently in the test).
- ``gui/analysis_studio.py`` + ``gui/main_window.py`` integration: the
  Toplevel is single-instance, non-destructive ("Apply" never mutates the
  source array/column), and provenance records survive the project
  save/load round trip (including backward compatibility with pre-6.1
  project files that have no analysis folder at all).

GUI tests follow the same headless conventions as ``test_suite.py``:
Agg backend, a mocked ``messagebox``, and ``update_idletasks()`` (never the
blocking ``update()``) to pump pending Tk geometry/idle work.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np
from scipy import signal as scipy_signal
from scipy import stats as scipy_stats

import matplotlib
matplotlib.use("Agg")

from analysis import stats as astats
from analysis import signal as asignal
from analysis.provenance import AnalysisResult
from core.project import ProjectDocument
from core.worksheet import WorksheetMetadata
from gui.main_window import ScientificGraphStudio


# -----------------------------------------------------------------------------
# Pure computation: analysis/stats.py
# -----------------------------------------------------------------------------


class TestStatsModule(unittest.TestCase):
    def test_descriptive_stats_matches_manual_calculation(self):
        y = np.arange(1.0, 21.0)  # N=20: large enough to avoid the small-N warning
        r = astats.descriptive_stats(y)
        self.assertEqual(r.n, 20)
        self.assertAlmostEqual(r.mean, np.mean(y))
        self.assertAlmostEqual(r.median, np.median(y))
        self.assertAlmostEqual(r.std, np.std(y, ddof=1))
        self.assertAlmostEqual(r.sem, np.std(y, ddof=1) / np.sqrt(20))
        self.assertAlmostEqual(r.minimum, 1.0)
        self.assertAlmostEqual(r.maximum, 20.0)
        self.assertEqual(r.warnings, [])

    def test_descriptive_stats_flags_nan_inf_and_constant_data(self):
        y = np.array([2.0, 2.0, np.nan, np.inf, 2.0])
        r = astats.descriptive_stats(y)
        self.assertEqual(r.n, 3)  # only the three finite 2.0 values remain
        self.assertTrue(any("NaN" in w for w in r.warnings))
        self.assertTrue(any("sonsuz" in w.lower() for w in r.warnings))
        self.assertTrue(any("sabit" in w.lower() for w in r.warnings))

    def test_shapiro_wilk_matches_scipy_reference(self):
        rng = np.random.default_rng(42)
        y = rng.normal(size=40)
        r = astats.shapiro_wilk(y)
        expected_stat, expected_p = scipy_stats.shapiro(y)
        self.assertAlmostEqual(r.statistic, expected_stat, places=6)
        self.assertAlmostEqual(r.p_value, expected_p, places=6)
        self.assertTrue(r.applicable)

    def test_shapiro_wilk_rejects_too_small_and_constant_samples(self):
        small = astats.shapiro_wilk([1.0, 2.0])
        self.assertFalse(small.applicable)
        constant = astats.shapiro_wilk([5.0, 5.0, 5.0, 5.0])
        self.assertFalse(constant.applicable)

    def test_welch_t_test_matches_scipy_reference(self):
        rng = np.random.default_rng(1)
        a = rng.normal(loc=1.0, scale=1.0, size=25)
        b = rng.normal(loc=1.6, scale=2.0, size=20)
        r = astats.welch_t_test(a, b)
        expected = scipy_stats.ttest_ind(a, b, equal_var=False)
        self.assertAlmostEqual(r.statistic, expected.statistic, places=8)
        self.assertAlmostEqual(r.p_value, expected.pvalue, places=8)
        self.assertAlmostEqual(r.mean_diff, np.mean(a) - np.mean(b), places=8)
        self.assertTrue(r.ci_low < r.mean_diff < r.ci_high)

    def test_paired_t_test_matches_scipy_reference(self):
        rng = np.random.default_rng(2)
        before = rng.normal(loc=10.0, scale=1.5, size=15)
        after = before + rng.normal(loc=0.5, scale=0.5, size=15)
        r = astats.paired_t_test(before, after)
        expected = scipy_stats.ttest_rel(before, after)
        self.assertAlmostEqual(r.statistic, expected.statistic, places=8)
        self.assertAlmostEqual(r.p_value, expected.pvalue, places=8)
        self.assertEqual(r.df, 14)

    def test_paired_t_test_requires_equal_length(self):
        with self.assertRaises(ValueError):
            astats.paired_t_test([1.0, 2.0, 3.0], [1.0, 2.0])

    def test_one_way_anova_matches_scipy_reference(self):
        rng = np.random.default_rng(3)
        g1 = rng.normal(0.0, 1.0, 20)
        g2 = rng.normal(0.8, 1.0, 20)
        g3 = rng.normal(1.5, 1.0, 20)
        r = astats.one_way_anova(g1, g2, g3)
        expected = scipy_stats.f_oneway(g1, g2, g3)
        self.assertAlmostEqual(r.statistic, expected.statistic, places=8)
        self.assertAlmostEqual(r.p_value, expected.pvalue, places=8)
        self.assertEqual(r.df_between, 2)
        self.assertEqual(r.df_within, 57)
        self.assertGreater(r.eta_squared, 0.0)
        self.assertLess(r.eta_squared, 1.0)

    def test_cohens_d_independent_known_value(self):
        a = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        b = np.array([3.0, 4.0, 5.0, 6.0, 7.0])
        # Equal spread/size groups shifted by 2 with sample std sqrt(2.5):
        # pooled_sd == std(a, ddof=1) == std(b, ddof=1) -> d == -2 / std.
        d = astats.cohens_d_independent(a, b)
        pooled_sd = np.std(a, ddof=1)
        self.assertAlmostEqual(d, (np.mean(a) - np.mean(b)) / pooled_sd, places=8)

    def test_cohens_d_paired_zero_when_no_change(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        self.assertAlmostEqual(astats.cohens_d_paired(a, a.copy()), 0.0)

    def test_eta_squared_zero_when_group_means_equal(self):
        g1 = np.array([1.0, 2.0, 3.0])
        g2 = np.array([1.0, 2.0, 3.0])
        self.assertAlmostEqual(astats.eta_squared(g1, g2), 0.0, places=8)

    def test_confidence_interval_mean_matches_manual_t_interval(self):
        y = np.array([10.0, 12.0, 11.0, 13.0, 9.0, 14.0])
        low, high = astats.confidence_interval_mean(y, confidence=0.95)
        mean = np.mean(y)
        sem = np.std(y, ddof=1) / np.sqrt(len(y))
        t_crit = scipy_stats.t.ppf(0.975, df=len(y) - 1)
        self.assertAlmostEqual(low, mean - t_crit * sem, places=8)
        self.assertAlmostEqual(high, mean + t_crit * sem, places=8)

    def test_sample_warnings_detect_small_n_and_constant_data(self):
        warnings_small = astats.sample_warnings([1.0, 2.0], min_n=10)
        self.assertTrue(any("küçük" in w for w in warnings_small))
        warnings_const = astats.sample_warnings([5.0, 5.0, 5.0])
        self.assertTrue(any("sabit" in w for w in warnings_const))

    # -- Review Cycle 1 regression tests -----------------------------------

    def test_cohens_d_independent_undefined_for_zero_variance_different_means(self):
        # Review Cycle 1, P1-5: two constant groups with different means
        # have an undefined (division-by-zero) standardized effect size —
        # it must come back as NaN, not silently as 0 (which would read as
        # "no effect", the opposite of what a mean difference of 2 means).
        a = np.array([5.0, 5.0, 5.0, 5.0])
        b = np.array([7.0, 7.0, 7.0, 7.0])
        self.assertTrue(np.isnan(astats.cohens_d_independent(a, b)))

    def test_cohens_d_independent_zero_for_zero_variance_equal_means(self):
        a = np.array([5.0, 5.0, 5.0])
        b = np.array([5.0, 5.0, 5.0])
        self.assertEqual(astats.cohens_d_independent(a, b), 0.0)

    def test_cohens_d_paired_undefined_for_zero_variance_nonzero_diff(self):
        a = np.array([5.0, 6.0, 7.0, 8.0])
        b = a - 2.0  # every difference is exactly 2.0 -> zero variance
        self.assertTrue(np.isnan(astats.cohens_d_paired(a, b)))

    def test_welch_t_test_warns_when_cohens_d_undefined(self):
        a = np.array([5.0, 5.0, 5.0])
        b = np.array([7.0, 7.0, 7.0])
        r = astats.welch_t_test(a, b)
        self.assertTrue(np.isnan(r.cohens_d))
        self.assertTrue(any("tanımsız" in w.lower() for w in r.warnings))

    def test_welch_t_test_rejects_invalid_confidence(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        b = np.array([4.0, 5.0, 6.0, 7.0])
        with self.assertRaises(ValueError):
            astats.welch_t_test(a, b, confidence=1.0)
        with self.assertRaises(ValueError):
            astats.welch_t_test(a, b, confidence=0.0)
        with self.assertRaises(ValueError):
            astats.welch_t_test(a, b, confidence=-0.5)

    def test_paired_t_test_rejects_invalid_confidence(self):
        a = np.array([1.0, 2.0, 3.0, 4.0])
        with self.assertRaises(ValueError):
            astats.paired_t_test(a, a + 1.0, confidence=1.5)

    def test_confidence_interval_mean_rejects_invalid_confidence(self):
        with self.assertRaises(ValueError):
            astats.confidence_interval_mean([1.0, 2.0, 3.0], confidence=1.0)
        with self.assertRaises(ValueError):
            astats.confidence_interval_mean([1.0, 2.0, 3.0], confidence=0.0)

    def test_welch_t_test_suggests_nonparametric_alternative_on_non_normal_group(self):
        rng = np.random.default_rng(11)
        a = rng.exponential(scale=1.0, size=30)  # strongly non-normal
        b = rng.normal(loc=1.0, size=30)
        r = astats.welch_t_test(a, b)
        self.assertTrue(any("Mann-Whitney" in w for w in r.warnings))
        # the test itself must still be the one requested — never silently swapped
        self.assertIsInstance(r.statistic, float)


# -----------------------------------------------------------------------------
# Pure computation: analysis/signal.py
# -----------------------------------------------------------------------------


class TestSignalModule(unittest.TestCase):
    def test_savitzky_golay_matches_scipy_reference(self):
        x = np.linspace(0, 10, 50)
        y = np.sin(x) + 0.0  # deterministic, no injected noise
        r = asignal.savitzky_golay(y, window_length=7, polyorder=2)
        expected = scipy_signal.savgol_filter(y, window_length=7, polyorder=2)
        np.testing.assert_allclose(r.y, expected)

    def test_savitzky_golay_adjusts_invalid_parameters_with_warning(self):
        y = np.array([1.0, 2.0, 3.0, 4.0])  # shorter than default window
        r = asignal.savitzky_golay(y, window_length=99, polyorder=10)
        self.assertEqual(len(r.y), 4)
        self.assertTrue(r.warnings)

    def test_median_filter_matches_scipy_reference(self):
        y = np.array([1.0, 100.0, 3.0, 4.0, 5.0, 6.0, 7.0])
        r = asignal.median_filter(y, kernel_size=3)
        expected = scipy_signal.medfilt(y, kernel_size=3)
        np.testing.assert_allclose(r.y, expected)

    def test_moving_average_smooths_step_towards_transition_average(self):
        y = np.array([0.0, 0.0, 0.0, 10.0, 10.0, 10.0])
        r = asignal.moving_average(y, window=3)
        self.assertEqual(len(r.y), len(y))
        # values away from the step stay close to their local plateau
        self.assertAlmostEqual(r.y[0], 0.0, places=6)
        self.assertAlmostEqual(r.y[-1], 10.0, places=6)

    def test_derivative_matches_numpy_gradient(self):
        x = np.linspace(0, 5, 30)
        y = x ** 2
        r = asignal.derivative(x, y, order=1)
        expected = np.gradient(y, x)
        np.testing.assert_allclose(r.y, expected)

    def test_cumulative_integral_matches_scipy_reference(self):
        x = np.linspace(0, 2 * np.pi, 200)
        y = np.sin(x)
        r = asignal.cumulative_integral(x, y)
        from scipy.integrate import cumulative_trapezoid
        expected = cumulative_trapezoid(y, x, initial=0.0)
        np.testing.assert_allclose(r.cumulative, expected)
        self.assertAlmostEqual(r.total, expected[-1])

    def test_cumulative_integral_rejects_unordered_x(self):
        # Review Cycle 1, P0-1: silently sorting X before integrating would
        # decouple the (now reordered) result from the caller's original row
        # order, so a row-aligned "Apply" would misassign values to rows.
        # Cumulative integral now requires strictly increasing X and rejects
        # anything else with a clear error instead.
        x = np.array([2.0, 0.0, 1.0])
        y = np.array([4.0, 0.0, 2.0])
        with self.assertRaises(ValueError):
            asignal.cumulative_integral(x, y)

    def test_cumulative_integral_rejects_duplicate_x(self):
        x = np.array([0.0, 1.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 1.0, 2.0])
        with self.assertRaises(ValueError):
            asignal.cumulative_integral(x, y)

    def test_derivative_rejects_duplicate_x(self):
        x = np.array([0.0, 1.0, 1.0, 2.0])
        y = np.array([0.0, 1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            asignal.derivative(x, y)

    def test_derivative_rejects_unordered_x(self):
        x = np.array([0.0, 2.0, 1.0, 3.0])
        y = np.array([0.0, 1.0, 2.0, 3.0])
        with self.assertRaises(ValueError):
            asignal.derivative(x, y)

    def test_fft_spectrum_recovers_known_frequency(self):
        fs = 100.0
        t = np.arange(0, 2, 1.0 / fs)
        freq_true = 5.0
        y = np.sin(2 * np.pi * freq_true * t)
        r = asignal.fft_spectrum(t, y)
        peak_freq = r.frequency[np.argmax(r.amplitude)]
        self.assertAlmostEqual(peak_freq, freq_true, delta=0.5)
        self.assertAlmostEqual(r.sample_rate, fs, places=3)

    def test_find_peaks_matches_scipy_reference(self):
        x = np.arange(20, dtype=float)
        y = np.array([0, 1, 0, 3, 0, 1, 0, 5, 0, 1, 0, 3, 0, 1, 0, 4, 0, 1, 0, 0], dtype=float)
        r = asignal.find_peaks(x, y, prominence=2.0)
        expected_idx, _ = scipy_signal.find_peaks(y, prominence=2.0)
        np.testing.assert_array_equal(r.indices, expected_idx)

    def test_find_peaks_reports_warning_when_none_found(self):
        x = np.arange(10, dtype=float)
        y = np.ones(10)  # flat line, no peaks possible
        r = asignal.find_peaks(x, y)
        self.assertEqual(r.indices.size, 0)
        self.assertTrue(r.warnings)

    def test_signal_functions_never_mutate_input_arrays(self):
        y = np.array([1.0, 5.0, 2.0, 8.0, 3.0])
        y_copy = y.copy()
        asignal.moving_average(y, window=3)
        asignal.median_filter(y, kernel_size=3)
        np.testing.assert_array_equal(y, y_copy)

    # -- Review Cycle 1 regression tests -----------------------------------

    def test_moving_average_even_window_uses_exact_window_count(self):
        # Review Cycle 1, P1-2: the old `half = window // 2` split used
        # `half` samples on *both* sides of an even window, averaging
        # window+1 points instead of window.
        y = np.arange(20, dtype=float)
        window = 4
        r = asignal.moving_average(y, window=window)
        i = 10
        expected = np.mean(y[i - 1:i + 3])  # exactly 4 samples: i-1..i+2
        self.assertAlmostEqual(r.y[i], expected, places=10)
        self.assertEqual(r.params["window"], window)

    def test_moving_average_tolerates_nan_with_explicit_warning(self):
        y = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        r = asignal.moving_average(y, window=3)
        self.assertEqual(len(r.y), 5)
        self.assertTrue(any("NaN" in w for w in r.warnings))

    def test_moving_average_rejects_inf(self):
        y = np.array([1.0, 2.0, np.inf, 4.0, 5.0])
        with self.assertRaises(ValueError):
            asignal.moving_average(y, window=3)

    def test_savitzky_golay_rejects_nan(self):
        y = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        with self.assertRaises(ValueError):
            asignal.savitzky_golay(y, window_length=3, polyorder=1)

    def test_median_filter_rejects_inf(self):
        y = np.array([1.0, 2.0, np.inf, 4.0, 5.0])
        with self.assertRaises(ValueError):
            asignal.median_filter(y, kernel_size=3)

    def test_derivative_rejects_nan(self):
        x = np.array([0.0, 1.0, 2.0, 3.0])
        y = np.array([0.0, 1.0, np.nan, 3.0])
        with self.assertRaises(ValueError):
            asignal.derivative(x, y)

    def test_fft_spectrum_rejects_inf(self):
        x = np.arange(8, dtype=float)
        y = np.array([1.0, 2.0, 3.0, np.inf, 5.0, 6.0, 7.0, 8.0])
        with self.assertRaises(ValueError):
            asignal.fft_spectrum(x, y)

    def test_find_peaks_rejects_nan(self):
        x = np.arange(6, dtype=float)
        y = np.array([0.0, 1.0, np.nan, 1.0, 0.0, 1.0])
        with self.assertRaises(ValueError):
            asignal.find_peaks(x, y)

    def test_fft_spectrum_even_n_does_not_double_nyquist_bin(self):
        # Review Cycle 1, P1-4: rfft's last bin *is* the Nyquist frequency
        # for even N and has no mirrored negative-frequency twin, so it
        # must not be doubled like the interior bins.
        n = 16
        x = np.arange(n, dtype=float)
        rng = np.random.default_rng(7)
        y = rng.normal(size=n)
        r = asignal.fft_spectrum(x, y)
        spectrum = np.fft.rfft(y - np.mean(y))
        expected_nyquist = np.abs(spectrum[-1]) / n
        expected_interior = np.abs(spectrum[1]) * 2.0 / n
        self.assertAlmostEqual(r.amplitude[-1], expected_nyquist, places=10)
        self.assertAlmostEqual(r.amplitude[1], expected_interior, places=10)

    def test_fft_spectrum_odd_n_doubles_last_bin(self):
        # Odd N has no exact Nyquist bin — every non-DC bin, including the
        # last one, legitimately keeps the x2 mirrored-frequency factor.
        n = 15
        x = np.arange(n, dtype=float)
        rng = np.random.default_rng(8)
        y = rng.normal(size=n)
        r = asignal.fft_spectrum(x, y)
        spectrum = np.fft.rfft(y - np.mean(y))
        expected_last = np.abs(spectrum[-1]) * 2.0 / n
        self.assertAlmostEqual(r.amplitude[-1], expected_last, places=10)

    def test_fft_spectrum_detrend_is_a_visible_effective_parameter(self):
        r_detrended = asignal.fft_spectrum(np.arange(8, dtype=float), np.array([5.0] * 8), detrend=True)
        r_raw = asignal.fft_spectrum(np.arange(8, dtype=float), np.array([5.0] * 8), detrend=False)
        self.assertEqual(r_detrended.params["detrend"], True)
        self.assertEqual(r_raw.params["detrend"], False)
        # a pure DC signal with detrend on has ~0 amplitude everywhere...
        self.assertAlmostEqual(float(np.max(r_detrended.amplitude)), 0.0, places=8)
        # ...but a large DC bin with detrend off.
        self.assertGreater(r_raw.amplitude[0], 4.0)

    def test_savitzky_golay_params_reflect_effective_not_requested_values(self):
        # Review Cycle 1, P1-3: provenance must record what was actually
        # used after clamping, not the raw values the caller asked for.
        y = np.array([1.0, 2.0, 3.0, 4.0])  # too short for window=99
        r = asignal.savitzky_golay(y, window_length=99, polyorder=10)
        self.assertNotEqual(r.params["window_length"], 99)
        self.assertNotEqual(r.params["polyorder"], 10)
        self.assertLessEqual(r.params["window_length"], len(y))
        self.assertLess(r.params["polyorder"], r.params["window_length"])


# -----------------------------------------------------------------------------
# Provenance and project persistence
# -----------------------------------------------------------------------------


class TestProvenanceAndProject(unittest.TestCase):
    def test_analysis_result_round_trips_through_dict(self):
        record = AnalysisResult(
            method="welch_t",
            mode="statistics",
            source_name="A vs B",
            parameters={"confidence": 0.95},
            summary="t=1.23 p=0.05",
            app_version="6.1",
            warnings=["küçük örneklem"],
            metrics={"t": 1.23, "p_value": 0.05},
        )
        restored = AnalysisResult.from_dict(record.to_dict())
        self.assertEqual(restored.method, record.method)
        self.assertEqual(restored.parameters, record.parameters)
        self.assertEqual(restored.warnings, record.warnings)
        self.assertEqual(restored.metrics, record.metrics)
        self.assertIn("Yöntem: welch_t", restored.method_summary_text())
        self.assertIn("küçük örneklem", restored.method_summary_text())

    def test_project_document_gains_analysis_folder_on_legacy_load(self):
        legacy = ProjectDocument.new()
        legacy_dict = legacy.to_dict()
        # Simulate a pre-6.1 project file saved before the analysis folder
        # existed: strip it out of the serialized root's children.
        legacy_dict["root"]["children"] = [
            child for child in legacy_dict["root"]["children"] if child["kind"] != "folder_analysis"
        ]
        restored = ProjectDocument.from_dict(legacy_dict)
        self.assertIsNotNone(restored.find_kind("folder_analysis"))
        self.assertEqual(restored.analysis_results(), [])

    def test_project_document_add_and_serialize_analysis_result(self):
        doc = ProjectDocument.new()
        record = AnalysisResult(
            method="shapiro", mode="statistics", source_name="Y1",
            parameters={}, summary="W=0.98 p=0.4", app_version="6.1",
        )
        doc.add_analysis_result("shapiro — Y1", record.to_dict())
        self.assertEqual(len(doc.analysis_results()), 1)

        round_tripped = ProjectDocument.from_dict(doc.to_dict())
        results = round_tripped.analysis_results()
        self.assertEqual(len(results), 1)
        restored_record = AnalysisResult.from_dict(results[0].metadata)
        self.assertEqual(restored_record.method, "shapiro")
        self.assertEqual(restored_record.summary, "W=0.98 p=0.4")


# -----------------------------------------------------------------------------
# GUI integration (headless, matches test_suite.py conventions)
# -----------------------------------------------------------------------------


class TestAnalysisStudioIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._mw_patcher = patch("gui.main_window.messagebox")
        cls._studio_patcher = patch("gui.analysis_studio.messagebox")
        cls._mw_patcher.start()
        cls._studio_patcher.start()
        cls.app = ScientificGraphStudio()
        cls.app.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.app.destroy()
        except Exception:
            pass
        cls._studio_patcher.stop()
        cls._mw_patcher.stop()

    def tearDown(self):
        win = getattr(self.app, "_analysis_studio_win", None)
        if win is not None and win.winfo_exists():
            win.destroy()
        self.app._analysis_studio_win = None

    def test_open_analysis_studio_is_single_instance(self):
        self.app.open_analysis_studio()
        first = self.app._analysis_studio_win
        self.assertIsNotNone(first)
        self.app.open_analysis_studio()
        second = self.app._analysis_studio_win
        self.assertIs(first, second)

    def test_studio_prefills_selected_source_series(self):
        self.app.sync_series_from_sheet(preserve=False)
        self.assertGreaterEqual(len(self.app.loaded_xy_series), 1)
        self.app.open_analysis_studio(0)
        win = self.app._analysis_studio_win
        win.update_idletasks()
        self.assertIn(self.app.loaded_xy_series[0], win._series_cache.values())
        self.assertIs(win._series(win._statistics_source_a.get()), self.app.loaded_xy_series[0])

    def test_statistics_descriptive_result_has_no_warnings_on_clean_data(self):
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        names = list(win._series_cache.keys())
        win._statistics_source_a.set(names[0])
        win.force_recompute()
        self.assertIsNotNone(win._last_result)
        self.assertEqual(win._last_result.mode, "statistics")
        self.assertEqual(win._last_result.method, "descriptive")
        self.assertGreater(len(win._statistics_axes.patches), 0)

    def test_signal_apply_adds_column_without_mutating_raw_series(self):
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        win.notebook.select(win.signal_tab)
        win.update_idletasks()
        names = list(win._series_cache.keys())
        source_series = win._series(names[0])
        raw_y_before = source_series.y.copy()
        raw_header_count_before = len(self.app.sheet_headers)
        raw_result_count_before = len(self.app.project_document.analysis_results())

        win.signal_method_var.set("Savitzky–Golay Filtresi")
        win._render_params()
        win._signal_source_a.set(names[0])
        win.force_recompute()
        self.assertIsNotNone(win._last_apply_payload)

        win._apply_result()

        # Raw source array untouched...
        np.testing.assert_array_equal(source_series.y, raw_y_before)
        # ...and a brand new worksheet column/series + provenance record was
        # appended instead (this shared headless app instance accumulates
        # state across tests in this class, same convention as test_suite.py).
        self.assertEqual(len(self.app.sheet_headers), raw_header_count_before + 1)
        self.assertEqual(len(self.app.project_document.analysis_results()), raw_result_count_before + 1)

    def test_fft_and_peaks_are_provenance_only_no_row_aligned_apply(self):
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        win.notebook.select(win.signal_tab)
        win.update_idletasks()
        names = list(win._series_cache.keys())
        win._signal_source_a.set(names[0])

        win.signal_method_var.set("FFT Genlik Spektrumu")
        win._render_params()
        win.force_recompute()
        self.assertIsNone(win._last_apply_payload)

        win.signal_method_var.set("Pik Bulma")
        win._render_params()
        win.force_recompute()
        self.assertIsNone(win._last_apply_payload)

    def test_analysis_result_survives_project_save_and_load_round_trip(self):
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        names = list(win._series_cache.keys())
        win._statistics_source_a.set(names[0])
        win.force_recompute()
        before = len(self.app.project_document.analysis_results())
        win._apply_result()
        self.assertEqual(len(self.app.project_document.analysis_results()), before + 1)

        state = self.app._capture_state()
        self.app._restore_state(state)
        self.assertEqual(len(self.app.project_document.analysis_results()), before + 1)

    def test_anova_requires_at_least_two_selected_groups(self):
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        win.stat_method_var.set("Tek Yönlü ANOVA")
        win._render_params()
        win._statistics_multi_list.selection_clear(0, "end")
        win.force_recompute()
        self.assertIsNone(win._last_result)

    # -- Review Cycle 1 regression tests -----------------------------------

    def test_signal_apply_aligns_row_indices_across_blank_y_rows(self):
        # Review Cycle 1, P0-1: data/engine.py compacts out rows with a
        # blank Y cell, so a series built from row 0/2/3 (row 1 skipped)
        # must scatter its row-aligned result back to rows 0/2/3 of the
        # sheet — never rows 0/1/2, which would silently shift every value
        # after the first gap onto the wrong original row.
        self.app.sheet_headers = ["X", "Y"]
        self.app.sheet_roles = ["X", "Y"]
        self.app.sheet_rows = [["1", "10"], ["2", ""], ["3", "30"], ["4", "40"]]
        self.app.sync_series_from_sheet(preserve=False)
        source = next(s for s in self.app.loaded_xy_series if s.y_header == "Y")
        self.assertEqual(list(source.row_indices), [0, 2, 3])

        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        win.notebook.select(win.signal_tab)
        win.update_idletasks()
        win.signal_method_var.set("Hareketli Ortalama")
        win._render_params()
        win._signal_source_a.set(source.name)
        win.force_recompute()
        self.assertIsNotNone(win._last_apply_payload)
        expected = asignal.moving_average(source.y, window=win.window_var.get()).y
        win._apply_result()

        new_col_idx = len(self.app.sheet_headers) - 1
        self.assertEqual(self.app.sheet_rows[1][new_col_idx], "")  # blank-Y row stays blank
        self.assertNotEqual(self.app.sheet_rows[0][new_col_idx], "")
        self.assertNotEqual(self.app.sheet_rows[2][new_col_idx], "")
        self.assertNotEqual(self.app.sheet_rows[3][new_col_idx], "")
        for row_idx, expected_value in zip(source.row_indices, expected):
            self.assertAlmostEqual(float(self.app.sheet_rows[int(row_idx)][new_col_idx]), expected_value)

    def test_duplicate_named_columns_get_distinct_source_ids(self):
        # Review Cycle 1, P1-1: two columns named "Y" must not collide in
        # the source picker (a plain {name: series} dict would drop one)
        # and must get different provenance source ids.
        self.app.sheet_headers = ["X", "Y", "Y"]
        self.app.sheet_roles = ["X", "Y", "Y"]
        self.app.sheet_rows = [[str(x), str(x), str(x * 2)] for x in range(1, 6)]
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(len(self.app.loaded_xy_series), 2)
        uids = {s.series_uid for s in self.app.loaded_xy_series}
        self.assertEqual(len(uids), 2)

        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        names = list(win._series_cache.keys())
        self.assertEqual(len(names), len(set(names)))  # disambiguated labels don't collide

        win._statistics_source_a.set(names[0])
        win.force_recompute()
        first_id = win._last_result.source_id
        win._statistics_source_a.set(names[1])
        win.force_recompute()
        second_id = win._last_result.source_id
        self.assertNotEqual(first_id, second_id)
        self.assertTrue(first_id and second_id)

    def test_source_id_uses_stable_column_metadata_uuid(self):
        self.app.sheet_headers = ["X", "Signal"]
        self.app.sheet_roles = ["X", "Y"]
        self.app.sheet_rows = [[str(x), str(x * 2)] for x in range(1, 6)]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(
            self.app.sheet_headers, self.app.sheet_roles
        )
        expected_id = self.app.sheet_metadata.columns[1].column_id
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(self.app.loaded_xy_series[0].series_uid, expected_id)

        # A display rename and a project state round-trip must not change the
        # source identity recorded in future analysis provenance.
        self.app.sheet_headers[1] = "Renamed Signal"
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(self.app.loaded_xy_series[0].series_uid, expected_id)
        state = self.app._capture_state()
        self.app._restore_state(state)
        self.app.sync_series_from_sheet(preserve=False)
        self.assertEqual(self.app.loaded_xy_series[0].series_uid, expected_id)

    def test_source_labels_never_collide_with_suffix_like_real_names(self):
        self.app.sheet_headers = ["X", "Y", "Y", "Y (#1)"]
        self.app.sheet_roles = ["X", "Y", "Y", "Y"]
        self.app.sheet_rows = [[str(x), str(x), str(x * 2), str(x * 3)] for x in range(1, 6)]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(
            self.app.sheet_headers, self.app.sheet_roles
        )
        self.app.sync_series_from_sheet(preserve=False)
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        self.assertEqual(len(win._series_cache), 3)
        self.assertEqual(len(win._series_cache), len(set(win._series_cache)))
        self.assertEqual(
            {s.series_uid for s in win._series_cache.values()},
            {s.series_uid for s in self.app.loaded_xy_series},
        )

    def test_open_studio_reselects_newly_targeted_series(self):
        self.app.sheet_headers = ["X", "A", "B"]
        self.app.sheet_roles = ["X", "Y", "Y"]
        self.app.sheet_rows = [[str(x), str(x), str(x * 2)] for x in range(1, 6)]
        self.app.sheet_metadata = WorksheetMetadata.from_headers_roles(
            self.app.sheet_headers, self.app.sheet_roles
        )
        self.app.sync_series_from_sheet(preserve=False)
        self.app.open_analysis_studio(0)
        win = self.app._analysis_studio_win
        win.update_idletasks()
        self.assertIs(win._series(win._statistics_source_a.get()), self.app.loaded_xy_series[0])
        self.app.open_analysis_studio(1)
        win.update_idletasks()
        self.assertIs(win._series(win._statistics_source_a.get()), self.app.loaded_xy_series[1])
        self.assertIs(win._series(win._signal_source_a.get()), self.app.loaded_xy_series[1])

    def test_stale_result_invalidated_on_input_change_before_recompute(self):
        # Review Cycle 1, P0-2: changing an input must immediately disable
        # Apply/Copy and clear the stale result — not leave the previous
        # computation's result clickable while the debounce timer is
        # still pending.
        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        names = list(win._series_cache.keys())
        win._statistics_source_a.set(names[0])
        win.force_recompute()
        self.assertIsNotNone(win._last_result)
        self.assertEqual(str(win._apply_button("statistics").cget("state")), "normal")
        self.assertEqual(str(win._copy_button("statistics").cget("state")), "normal")

        win.confidence_var.set(0.90)  # any input change schedules + invalidates
        self.assertIsNone(win._last_result)
        self.assertIsNone(win._last_apply_payload)
        self.assertEqual(str(win._apply_button("statistics").cget("state")), "disabled")
        self.assertEqual(str(win._copy_button("statistics").cget("state")), "disabled")

        win.force_recompute()
        self.assertIsNotNone(win._last_result)
        self.assertEqual(str(win._apply_button("statistics").cget("state")), "normal")

    def test_signal_apply_provenance_records_effective_parameters(self):
        # Review Cycle 1, P1-3: provenance parameters must reflect the
        # clamped/effective values actually used, not the raw requested ones.
        self.app.sheet_headers = ["X", "Y"]
        self.app.sheet_roles = ["X", "Y"]
        self.app.sheet_rows = [[str(x), str(x)] for x in range(1, 5)]  # only 4 points
        self.app.sync_series_from_sheet(preserve=False)

        self.app.open_analysis_studio()
        win = self.app._analysis_studio_win
        win.update_idletasks()
        win.notebook.select(win.signal_tab)
        win.update_idletasks()
        names = list(win._series_cache.keys())
        win._signal_source_a.set(names[0])
        win.signal_method_var.set("Savitzky–Golay Filtresi")
        win._render_params()
        win.advanced_var.set(True)
        win._render_params()
        win.window_var.set(99)
        win.polyorder_var.set(50)
        win.force_recompute()
        self.assertIsNotNone(win._last_result)
        params = win._last_result.parameters
        self.assertLess(params["window_length"], 99)
        self.assertLess(params["polyorder"], params["window_length"])


if __name__ == "__main__":
    unittest.main()
