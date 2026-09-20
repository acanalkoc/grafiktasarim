"""Pure, SciPy-backed statistical routines for the Scientific Analysis Studio.

No Tk, matplotlib or project-state imports here — every function takes plain
NumPy-convertible sequences and returns a small dataclass, so it can be unit
tested in isolation and reused by any future caller. GUI code in
``gui/analysis_studio.py`` orchestrates these functions and attaches
provenance (see ``analysis/provenance.py``).

Known statistics (Shapiro-Wilk, Welch/paired t-test, one-way ANOVA) are
computed with SciPy's reference implementations. Effect sizes and confidence
intervals that SciPy does not provide directly (Cohen's d, eta-squared, CI of
the mean/mean-difference) are small, testable formulas defined here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
from scipy import stats as _stats

MIN_SHAPIRO_N = 3
MAX_SHAPIRO_N = 5000
SMALL_SAMPLE_N = 10


def _as_array(y: Sequence[float]) -> np.ndarray:
    return np.asarray(y, dtype=float)


def finite_values(y: Sequence[float]) -> np.ndarray:
    """Return only the finite (non-NaN, non-Inf) values of ``y``."""
    arr = _as_array(y)
    return arr[np.isfinite(arr)]


def _non_finite_warnings(y: np.ndarray) -> list[str]:
    warnings: list[str] = []
    if y.size == 0:
        return warnings
    n_nan = int(np.isnan(y).sum())
    n_inf = int(np.isinf(y).sum())
    if n_nan:
        warnings.append(f"{n_nan} adet NaN değer bulundu ve hesaplamadan çıkarıldı.")
    if n_inf:
        warnings.append(f"{n_inf} adet sonsuz (Inf) değer bulundu ve hesaplamadan çıkarıldı.")
    return warnings


def _constant_warning(clean: np.ndarray) -> list[str]:
    if clean.size > 1 and np.allclose(clean, clean[0]):
        return ["Veri sabit (tüm değerler eşit); varyans/normallik/etkileşim testleri anlamsız olabilir."]
    return []


def _small_sample_warning(n: int, *, minimum: int = SMALL_SAMPLE_N) -> list[str]:
    if 0 < n < minimum:
        return [f"Örneklem büyüklüğü küçük (N={n}); sonuçlar dikkatle yorumlanmalıdır."]
    return []


def _validate_confidence(confidence: float) -> None:
    if not (0.0 < float(confidence) < 1.0):
        raise ValueError("Güven düzeyi (confidence) 0 ile 1 arasında olmalıdır (örn. 0.95).")


_NONPARAMETRIC_ALTERNATIVES: dict[str, str] = {
    "welch_t": "Mann-Whitney U testi",
    "paired_t": "Wilcoxon işaretli sıra testi",
    "anova": "Kruskal-Wallis testi",
}


def _normality_alternative_warning(test_key: str, *clean_groups: np.ndarray) -> list[str]:
    """Bir grup normallik varsayımını karşılamıyorsa gerekçeli bir alternatif
    test önerisi döndürür. Testi kullanıcı adına DEĞİŞTİRMEZ — yalnızca
    görünür bir uyarı ekler (bkz. Bilimsel UX ilkeleri)."""
    alt = _NONPARAMETRIC_ALTERNATIVES.get(test_key)
    if alt is None:
        return []
    for g in clean_groups:
        if g.size < MIN_SHAPIRO_N or np.allclose(g, g[0]):
            continue
        try:
            _, p = _stats.shapiro(g)
        except Exception:
            continue
        if p < 0.05:
            return [
                f"Bir veya daha fazla grup normal dağılım varsayımını karşılamıyor gibi görünüyor "
                f"(Shapiro–Wilk p<0.05); alternatif olarak {alt} değerlendirilebilir "
                f"(test otomatik olarak değiştirilmedi)."
            ]
    return []


# ---------------------------------------------------------------------------
# Descriptive statistics
# ---------------------------------------------------------------------------


@dataclass
class DescriptiveStats:
    n: int
    mean: float
    median: float
    std: float
    sem: float
    minimum: float
    maximum: float
    value_range: float
    variance: float
    total: float
    warnings: list[str] = field(default_factory=list)


def descriptive_stats(y: Sequence[float]) -> DescriptiveStats:
    """Tanımlayıcı istatistikler: N, ortalama, medyan, std, SEM, min/max, ..."""
    raw = _as_array(y)
    warnings = _non_finite_warnings(raw)
    clean = raw[np.isfinite(raw)]
    if clean.size == 0:
        raise ValueError("Tanımlayıcı istatistik için geçerli (sonlu) veri yok.")
    n = int(clean.size)
    std = float(np.std(clean, ddof=1)) if n > 1 else 0.0
    sem = float(std / np.sqrt(n)) if n > 1 else 0.0
    warnings += _small_sample_warning(n) + _constant_warning(clean)
    return DescriptiveStats(
        n=n,
        mean=float(np.mean(clean)),
        median=float(np.median(clean)),
        std=std,
        sem=sem,
        minimum=float(np.min(clean)),
        maximum=float(np.max(clean)),
        value_range=float(np.max(clean) - np.min(clean)),
        variance=float(np.var(clean, ddof=1)) if n > 1 else 0.0,
        total=float(np.sum(clean)),
        warnings=warnings,
    )


def confidence_interval_mean(y: Sequence[float], confidence: float = 0.95) -> tuple[float, float]:
    """Ortalama için t-dağılımı tabanlı güven aralığı (SciPy'da doğrudan yok)."""
    _validate_confidence(confidence)
    clean = finite_values(y)
    n = clean.size
    if n < 2:
        raise ValueError("Güven aralığı için en az 2 geçerli gözlem gereklidir.")
    mean = float(np.mean(clean))
    sem = float(np.std(clean, ddof=1) / np.sqrt(n))
    if sem == 0.0:
        return (mean, mean)
    t_crit = float(_stats.t.ppf(0.5 + confidence / 2.0, df=n - 1))
    margin = t_crit * sem
    return (mean - margin, mean + margin)


# ---------------------------------------------------------------------------
# Normality
# ---------------------------------------------------------------------------


@dataclass
class NormalityResult:
    statistic: float
    p_value: float
    n: int  # = n_total, kept for backward compatibility with existing callers
    applicable: bool
    warnings: list[str] = field(default_factory=list)
    # v6.1 P3: N>5000 truncates the sample actually fed to scipy.stats.shapiro
    # (that reference implementation is not validated for arbitrarily large
    # N); n_total/n_analyzed make that truncation visible in provenance
    # instead of a single ambiguous ``n`` (V62 requirements §8).
    n_total: int = 0
    n_analyzed: int = 0

    def __post_init__(self) -> None:
        if not self.n_total:
            self.n_total = self.n
        if not self.n_analyzed:
            self.n_analyzed = min(self.n_total, MAX_SHAPIRO_N) if self.n_total else 0


def shapiro_wilk(y: Sequence[float]) -> NormalityResult:
    """Shapiro–Wilk normallik testi (``scipy.stats.shapiro`` referans uygulaması)."""
    raw = _as_array(y)
    warnings = _non_finite_warnings(raw)
    clean = raw[np.isfinite(raw)]
    n_total = int(clean.size)
    if n_total < MIN_SHAPIRO_N:
        return NormalityResult(
            statistic=float("nan"), p_value=float("nan"), n=n_total, applicable=False,
            warnings=warnings + ["Shapiro–Wilk testi için en az 3 gözlem gereklidir."],
            n_total=n_total, n_analyzed=n_total,
        )
    n_analyzed = n_total
    if n_total > MAX_SHAPIRO_N:
        clean = clean[:MAX_SHAPIRO_N]
        n_analyzed = MAX_SHAPIRO_N
        warnings.append(
            f"Shapiro–Wilk N>{MAX_SHAPIRO_N} olduğundan ilk {MAX_SHAPIRO_N} gözlemle sınırlandırıldı "
            f"(n_total={n_total}, n_analyzed={n_analyzed})."
        )
    if np.allclose(clean, clean[0]):
        return NormalityResult(
            statistic=1.0, p_value=0.0, n=n_total, applicable=False,
            warnings=warnings + ["Veri sabit; normallik testi tanımsızdır."],
            n_total=n_total, n_analyzed=n_analyzed,
        )
    statistic, p_value = _stats.shapiro(clean)
    warnings += _small_sample_warning(n_total)
    if p_value < 0.05:
        warnings.append("Shapiro–Wilk normal dağılım varsayımını reddediyor (p < 0.05).")
    return NormalityResult(
        statistic=float(statistic), p_value=float(p_value), n=n_total, applicable=True, warnings=warnings,
        n_total=n_total, n_analyzed=n_analyzed,
    )


def json_safe_float(value: float) -> Optional[float]:
    """Strict-JSON-safe serialization for a possibly NaN/Inf float.

    ``json.dumps(..., allow_nan=False)`` raises on NaN/Infinity, which are
    not valid JSON tokens even though Python's default encoder emits them.
    Effect sizes like Cohen's d can be genuinely undefined (0/0); callers
    serialize that as ``None`` (JSON ``null``) plus an ``*_applicable=False``
    sibling flag instead — see ``effect_size_json`` and V62 requirements §8.
    In-app computation keeps using the float/NaN value untouched.
    """
    value = float(value)
    return value if np.isfinite(value) else None


def effect_size_json(value: float) -> tuple[Optional[float], bool]:
    """Return ``(json_value, applicable)`` for an effect size that may be NaN."""
    safe = json_safe_float(value)
    return safe, safe is not None


# ---------------------------------------------------------------------------
# Effect sizes (small, testable formulas — not provided directly by SciPy)
# ---------------------------------------------------------------------------


def cohens_d_independent(a: Sequence[float], b: Sequence[float]) -> float:
    """Cohen's d for two independent samples using the pooled standard deviation."""
    a, b = finite_values(a), finite_values(b)
    n1, n2 = a.size, b.size
    if n1 < 2 or n2 < 2:
        raise ValueError("Cohen's d için her grupta en az 2 gözlem gereklidir.")
    v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)
    pooled_sd = np.sqrt(((n1 - 1) * v1 + (n2 - 1) * v2) / (n1 + n2 - 2))
    mean_diff = np.mean(a) - np.mean(b)
    if pooled_sd == 0:
        # Zero variance in both groups: if the means also coincide the
        # effect is genuinely zero, but zero variance with a nonzero mean
        # difference makes standardized d undefined (division by 0) — NaN,
        # not a silent 0, so the caller can surface an explicit warning.
        return 0.0 if mean_diff == 0 else float("nan")
    return float(mean_diff / pooled_sd)


def cohens_d_paired(a: Sequence[float], b: Sequence[float]) -> float:
    """Cohen's d for paired samples using the standard deviation of the differences."""
    a, b = _as_array(a), _as_array(b)
    if a.size != b.size:
        raise ValueError("Eşleştirilmiş Cohen's d için iki grup aynı uzunlukta olmalıdır.")
    diff = a - b
    diff = diff[np.isfinite(diff)]
    if diff.size < 2:
        raise ValueError("Eşleştirilmiş Cohen's d için en az 2 geçerli çift gereklidir.")
    sd = np.std(diff, ddof=1)
    mean_diff = np.mean(diff)
    if sd == 0:
        return 0.0 if mean_diff == 0 else float("nan")
    return float(mean_diff / sd)


def eta_squared(*groups: Sequence[float]) -> float:
    """Eta-kare etki büyüklüğü (SS arası / SS toplam) tek yönlü ANOVA için."""
    clean_groups = [finite_values(g) for g in groups]
    clean_groups = [g for g in clean_groups if g.size > 0]
    if len(clean_groups) < 2:
        raise ValueError("Eta-kare için en az iki dolu grup gereklidir.")
    all_values = np.concatenate(clean_groups)
    grand_mean = np.mean(all_values)
    ss_between = sum(g.size * (np.mean(g) - grand_mean) ** 2 for g in clean_groups)
    ss_total = np.sum((all_values - grand_mean) ** 2)
    if ss_total == 0:
        return 0.0
    return float(ss_between / ss_total)


# ---------------------------------------------------------------------------
# Hypothesis tests
# ---------------------------------------------------------------------------


@dataclass
class TTestResult:
    statistic: float
    p_value: float
    df: float
    mean_diff: float
    cohens_d: float
    ci_low: float
    ci_high: float
    n1: int
    n2: int
    warnings: list[str] = field(default_factory=list)


def welch_t_test(a: Sequence[float], b: Sequence[float], confidence: float = 0.95) -> TTestResult:
    """Bağımsız örneklem Welch t-testi (eşit olmayan varyans varsayımı)."""
    _validate_confidence(confidence)
    raw_a, raw_b = _as_array(a), _as_array(b)
    warnings = _non_finite_warnings(raw_a) + _non_finite_warnings(raw_b)
    clean_a, clean_b = finite_values(a), finite_values(b)
    if clean_a.size < 2 or clean_b.size < 2:
        raise ValueError("Welch t-testi için her grupta en az 2 geçerli gözlem gereklidir.")
    warnings += _constant_warning(clean_a) + _constant_warning(clean_b)
    warnings += _small_sample_warning(clean_a.size) + _small_sample_warning(clean_b.size)

    result = _stats.ttest_ind(clean_a, clean_b, equal_var=False)
    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    df = float(getattr(result, "df", _welch_df(clean_a, clean_b)))

    n1, n2 = clean_a.size, clean_b.size
    v1, v2 = np.var(clean_a, ddof=1), np.var(clean_b, ddof=1)
    se = float(np.sqrt(v1 / n1 + v2 / n2))
    mean_diff = float(np.mean(clean_a) - np.mean(clean_b))
    if se > 0:
        t_crit = float(_stats.t.ppf(0.5 + confidence / 2.0, df=df))
        ci_low, ci_high = mean_diff - t_crit * se, mean_diff + t_crit * se
    else:
        ci_low, ci_high = mean_diff, mean_diff

    d = cohens_d_independent(clean_a, clean_b)
    if np.isnan(d):
        warnings.append("Gruplar sıfır varyanslı fakat ortalamaları farklı; Cohen's d tanımsızdır (NaN).")
    warnings += _normality_alternative_warning("welch_t", clean_a, clean_b)

    return TTestResult(
        statistic=statistic, p_value=p_value, df=df, mean_diff=mean_diff,
        cohens_d=d, ci_low=ci_low, ci_high=ci_high, n1=n1, n2=n2, warnings=warnings,
    )


def _welch_df(a: np.ndarray, b: np.ndarray) -> float:
    v1, v2 = np.var(a, ddof=1), np.var(b, ddof=1)
    n1, n2 = a.size, b.size
    num = (v1 / n1 + v2 / n2) ** 2
    den = (v1 / n1) ** 2 / (n1 - 1) + (v2 / n2) ** 2 / (n2 - 1)
    return float(num / den) if den > 0 else float(n1 + n2 - 2)


def paired_t_test(a: Sequence[float], b: Sequence[float], confidence: float = 0.95) -> TTestResult:
    """Eşleştirilmiş (bağımlı) örneklem t-testi."""
    _validate_confidence(confidence)
    raw_a, raw_b = _as_array(a), _as_array(b)
    if raw_a.size != raw_b.size:
        raise ValueError("Eşleştirilmiş t-testi için iki grup aynı uzunlukta olmalıdır.")
    warnings = _non_finite_warnings(raw_a) + _non_finite_warnings(raw_b)
    mask = np.isfinite(raw_a) & np.isfinite(raw_b)
    clean_a, clean_b = raw_a[mask], raw_b[mask]
    if clean_a.size < 2:
        raise ValueError("Eşleştirilmiş t-testi için en az 2 geçerli çift gereklidir.")
    diff = clean_a - clean_b
    warnings += _constant_warning(diff) + _small_sample_warning(clean_a.size)

    result = _stats.ttest_rel(clean_a, clean_b)
    statistic = float(result.statistic)
    p_value = float(result.pvalue)
    n = clean_a.size
    df = float(n - 1)
    mean_diff = float(np.mean(diff))
    sd_diff = float(np.std(diff, ddof=1))
    se = sd_diff / np.sqrt(n)
    if se > 0:
        t_crit = float(_stats.t.ppf(0.5 + confidence / 2.0, df=df))
        ci_low, ci_high = mean_diff - t_crit * se, mean_diff + t_crit * se
    else:
        ci_low, ci_high = mean_diff, mean_diff

    d = cohens_d_paired(clean_a, clean_b)
    if np.isnan(d):
        warnings.append("Farkların varyansı sıfır fakat ortalama fark sıfır değil; Cohen's d tanımsızdır (NaN).")
    warnings += _normality_alternative_warning("paired_t", diff)

    return TTestResult(
        statistic=statistic, p_value=p_value, df=df, mean_diff=mean_diff,
        cohens_d=d, ci_low=ci_low, ci_high=ci_high, n1=n, n2=n, warnings=warnings,
    )


@dataclass
class AnovaResult:
    statistic: float
    p_value: float
    df_between: int
    df_within: int
    eta_squared: float
    group_sizes: list[int]
    warnings: list[str] = field(default_factory=list)


def one_way_anova(*groups: Sequence[float]) -> AnovaResult:
    """Tek yönlü ANOVA (``scipy.stats.f_oneway`` referans uygulaması)."""
    if len(groups) < 2:
        raise ValueError("Tek yönlü ANOVA için en az iki grup gereklidir.")
    warnings: list[str] = []
    clean_groups = []
    for g in groups:
        raw = _as_array(g)
        warnings += _non_finite_warnings(raw)
        clean = raw[np.isfinite(raw)]
        if clean.size < 2:
            raise ValueError("ANOVA için her grupta en az 2 geçerli gözlem gereklidir.")
        warnings += _constant_warning(clean) + _small_sample_warning(clean.size)
        clean_groups.append(clean)

    result = _stats.f_oneway(*clean_groups)
    k = len(clean_groups)
    n_total = sum(g.size for g in clean_groups)
    warnings += _normality_alternative_warning("anova", *clean_groups)
    return AnovaResult(
        statistic=float(result.statistic), p_value=float(result.pvalue),
        df_between=k - 1, df_within=n_total - k,
        eta_squared=eta_squared(*clean_groups),
        group_sizes=[int(g.size) for g in clean_groups],
        warnings=warnings,
    )


def sample_warnings(y: Sequence[float], *, min_n: int = SMALL_SAMPLE_N) -> list[str]:
    """Genel örneklem doğrulama uyarıları: NaN/Inf, sabit veri, küçük N."""
    raw = _as_array(y)
    warnings = _non_finite_warnings(raw)
    clean = raw[np.isfinite(raw)]
    warnings += _small_sample_warning(clean.size, minimum=min_n) + _constant_warning(clean)
    return warnings
