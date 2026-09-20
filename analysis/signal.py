"""Pure, SciPy/NumPy-backed signal processing routines for the Analysis Studio.

Mirrors ``analysis/stats.py``: no Tk/plotting imports, deterministic
functions returning small dataclasses, safe to unit test directly. Every
function returns a *new* array — raw source arrays passed in are never
mutated, matching the "linked, non-destructive result" requirement.

Every result dataclass carries a ``params`` dict of the *effective*
parameters actually used (after any clamping/rounding), not just the values
requested by the caller — provenance should record reality, not intent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np
from scipy import signal as _signal
from scipy import integrate as _integrate

MIN_POINTS = 2


def _as_array(v: Sequence[float]) -> np.ndarray:
    return np.asarray(v, dtype=float)


def _odd(n: int) -> int:
    n = int(n)
    return n if n % 2 == 1 else n + 1


def _validate_signal_input(arr: np.ndarray, label: str, *, allow_nan: bool = False) -> list[str]:
    """Reject Inf outright (never meaningful for filtering/integration/FFT);
    reject NaN unless the caller explicitly tolerates it (moving average
    only), in which case a warning documents how many points were skipped —
    never silently propagate NaN/Inf into a result."""
    warnings: list[str] = []
    if arr.size and np.any(np.isinf(arr)):
        raise ValueError(f"{label} içinde sonsuz (Inf) değer bulundu; sinyal işleme için geçerli sonlu veri gereklidir.")
    nan_mask = np.isnan(arr) if arr.size else np.zeros(0, dtype=bool)
    if nan_mask.any():
        if not allow_nan:
            raise ValueError(f"{label} içinde NaN değer bulundu; sinyal işleme için geçerli sonlu veri gereklidir.")
        warnings.append(
            f"{label} içinde {int(nan_mask.sum())} adet NaN değer bulundu; bu noktalar yok sayılarak hesaplanmıştır."
        )
    return warnings


def _require_strictly_increasing(x: np.ndarray, label: str = "X") -> None:
    if x.size < 2:
        return
    diffs = np.diff(x)
    if np.any(diffs == 0):
        raise ValueError(f"{label} değerlerinde tekrarlı (aynı) değer bulundu; kesin artan {label} gereklidir.")
    if np.any(diffs < 0):
        raise ValueError(f"{label} değerleri artan sırada değil; kesin artan {label} gereklidir.")


@dataclass
class SeriesResult:
    x: np.ndarray
    y: np.ndarray
    warnings: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def moving_average(y: Sequence[float], window: int = 5) -> SeriesResult:
    """Merkezli hareketli ortalama (kenarlarda daralan pencere ile)."""
    arr = _as_array(y)
    n = arr.size
    if n < MIN_POINTS:
        raise ValueError("Hareketli ortalama için en az 2 veri noktası gereklidir.")
    warnings = _validate_signal_input(arr, "Y", allow_nan=True)
    window = max(1, int(window))
    if window > n:
        window = n
        warnings.append(f"Pencere boyutu örneklem büyüklüğüne ({n}) düşürüldü.")
    # Exactly `window` samples per point (when not clipped by an edge), split
    # as evenly as possible around i — NOT window+1: half//2 on both sides
    # double-counts the centre point for even windows.
    half_lo = (window - 1) // 2
    half_hi = window - 1 - half_lo
    out = np.empty(n, dtype=float)
    for i in range(n):
        lo = max(0, i - half_lo)
        hi = min(n, i + half_hi + 1)
        out[i] = np.nanmean(arr[lo:hi])
    if np.isnan(out).any():
        warnings.append("Sonuçta NaN değer kaldı (bazı pencereler tamamen NaN veriden oluşuyordu).")
    return SeriesResult(x=np.arange(n, dtype=float), y=out, warnings=warnings, params={"window": window})


def savitzky_golay(y: Sequence[float], window_length: int = 7, polyorder: int = 2) -> SeriesResult:
    """Savitzky–Golay filtresi (``scipy.signal.savgol_filter`` referans uygulaması)."""
    arr = _as_array(y)
    n = arr.size
    if n < 3:
        raise ValueError("Savitzky–Golay filtresi için en az 3 veri noktası gereklidir.")
    warnings = _validate_signal_input(arr, "Y")
    window_length = _odd(max(3, int(window_length)))
    if window_length > n:
        window_length = _odd(n if n % 2 == 1 else n - 1)
        warnings.append(f"Pencere uzunluğu örneklem büyüklüğüne uyacak şekilde {window_length} olarak ayarlandı.")
    polyorder = int(polyorder)
    if polyorder >= window_length:
        polyorder = max(1, window_length - 1)
        warnings.append(f"Polinom derecesi pencere uzunluğundan küçük olacak şekilde {polyorder} olarak ayarlandı.")
    filtered = _signal.savgol_filter(arr, window_length=window_length, polyorder=polyorder)
    return SeriesResult(
        x=np.arange(n, dtype=float), y=filtered, warnings=warnings,
        params={"window_length": window_length, "polyorder": polyorder},
    )


def median_filter(y: Sequence[float], kernel_size: int = 5) -> SeriesResult:
    """Medyan filtre (``scipy.signal.medfilt`` referans uygulaması)."""
    arr = _as_array(y)
    n = arr.size
    if n < 3:
        raise ValueError("Medyan filtre için en az 3 veri noktası gereklidir.")
    warnings = _validate_signal_input(arr, "Y")
    kernel_size = _odd(max(1, int(kernel_size)))
    if kernel_size > n:
        kernel_size = _odd(n if n % 2 == 1 else n - 1)
        warnings.append(f"Çekirdek boyutu örneklem büyüklüğüne uyacak şekilde {kernel_size} olarak ayarlandı.")
    filtered = _signal.medfilt(arr, kernel_size=kernel_size)
    return SeriesResult(x=np.arange(n, dtype=float), y=filtered, warnings=warnings, params={"kernel_size": kernel_size})


def derivative(x: Sequence[float], y: Sequence[float], order: int = 1) -> SeriesResult:
    """Sayısal türev (``numpy.gradient`` ile), isteğe bağlı yüksek dereceler için tekrarlı.

    X kesin artan olmalıdır — tekrarlı/azalan X değerleri sessizce sıralanıp
    hesaba katılmaz (satır hizası bozulur); açık bir hata ile reddedilir.
    """
    x_arr, y_arr = _as_array(x), _as_array(y)
    if x_arr.size != y_arr.size:
        raise ValueError("Türev için X ve Y aynı uzunlukta olmalıdır.")
    if x_arr.size < 2:
        raise ValueError("Türev için en az 2 veri noktası gereklidir.")
    warnings = _validate_signal_input(x_arr, "X") + _validate_signal_input(y_arr, "Y")
    _require_strictly_increasing(x_arr, "X")
    order = max(1, int(order))
    result = y_arr.copy()
    for _ in range(order):
        result = np.gradient(result, x_arr)
    return SeriesResult(x=x_arr.copy(), y=result, warnings=warnings, params={"order": order})


@dataclass
class IntegralResult:
    x: np.ndarray
    cumulative: np.ndarray
    total: float
    warnings: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def cumulative_integral(x: Sequence[float], y: Sequence[float]) -> IntegralResult:
    """Kümülatif trapez integrali (``scipy.integrate.cumulative_trapezoid``).

    X kesin artan olmalıdır. Sırasız/tekrarlı X'i sessizce sıralayıp
    hesaplamak, satır hizalı bir sonucu kaynak satırlarından koparır; bunun
    yerine açık bir hata ile reddedilir (bkz. derivative()).
    """
    x_arr, y_arr = _as_array(x), _as_array(y)
    if x_arr.size != y_arr.size:
        raise ValueError("İntegral için X ve Y aynı uzunlukta olmalıdır.")
    if x_arr.size < 2:
        raise ValueError("İntegral için en az 2 veri noktası gereklidir.")
    warnings = _validate_signal_input(x_arr, "X") + _validate_signal_input(y_arr, "Y")
    _require_strictly_increasing(x_arr, "X")
    cumulative = _integrate.cumulative_trapezoid(y_arr, x_arr, initial=0.0)
    return IntegralResult(x=x_arr.copy(), cumulative=cumulative, total=float(cumulative[-1]), warnings=warnings)


@dataclass
class FFTResult:
    frequency: np.ndarray
    amplitude: np.ndarray
    sample_rate: float
    warnings: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def fft_spectrum(x: Sequence[float], y: Sequence[float], *, detrend: bool = True) -> FFTResult:
    """Tek-taraflı FFT genlik spektrumu. Örnekleme aralığı X'in ortalama farkından türetilir.

    ``detrend``: DC/ortalama bileşenini çıkarır (varsayılan açık) — bu,
    sonucu etkileyen görünür bir parametredir ve provenance'a kaydedilir.
    """
    x_arr, y_arr = _as_array(x), _as_array(y)
    if x_arr.size != y_arr.size:
        raise ValueError("FFT için X ve Y aynı uzunlukta olmalıdır.")
    n = x_arr.size
    if n < 4:
        raise ValueError("FFT için en az 4 veri noktası gereklidir.")
    warnings = _validate_signal_input(x_arr, "X") + _validate_signal_input(y_arr, "Y")
    order = np.argsort(x_arr)
    x_sorted, y_sorted = x_arr[order], y_arr[order]
    diffs = np.diff(x_sorted)
    if diffs.size == 0 or np.any(diffs <= 0):
        raise ValueError("FFT için X değerleri kesin artan olmalıdır (tekrarlı X değeri bulundu).")
    dt = float(np.mean(diffs))
    if np.std(diffs) / dt > 0.01:
        warnings.append("X aralığı düzensiz; FFT ortalama örnekleme aralığı varsayılarak hesaplanmıştır.")

    signal_in = y_sorted - np.mean(y_sorted) if detrend else y_sorted
    spectrum = np.fft.rfft(signal_in)
    freq = np.fft.rfftfreq(n, d=dt)
    amplitude = np.abs(spectrum) * 2.0 / n
    if amplitude.size:
        # DC bin has no mirrored negative-frequency twin — don't double it.
        amplitude[0] = np.abs(spectrum[0]) / n
        # For even N, rfft's last bin is the exact Nyquist frequency, which
        # also has no mirrored twin (it is its own conjugate). Doubling it
        # inflates the Nyquist amplitude 2x. Odd N has no exact Nyquist bin,
        # so every remaining bin there is legitimately doubled.
        if n % 2 == 0 and amplitude.size > 1:
            amplitude[-1] = np.abs(spectrum[-1]) / n
    return FFTResult(
        frequency=freq, amplitude=amplitude, sample_rate=1.0 / dt if dt else 0.0, warnings=warnings,
        params={"detrend": bool(detrend)},
    )


@dataclass
class PeaksResult:
    indices: np.ndarray
    x: np.ndarray
    y: np.ndarray
    warnings: list[str] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)


def find_peaks(
    x: Sequence[float],
    y: Sequence[float],
    *,
    prominence: Optional[float] = None,
    distance: Optional[int] = None,
) -> PeaksResult:
    """Basit parametreli pik bulma (``scipy.signal.find_peaks`` referans uygulaması)."""
    x_arr, y_arr = _as_array(x), _as_array(y)
    if x_arr.size != y_arr.size:
        raise ValueError("Pik bulma için X ve Y aynı uzunlukta olmalıdır.")
    if x_arr.size < 3:
        raise ValueError("Pik bulma için en az 3 veri noktası gereklidir.")
    warnings = _validate_signal_input(x_arr, "X") + _validate_signal_input(y_arr, "Y")
    kwargs: dict[str, float] = {}
    if prominence is not None and prominence > 0:
        kwargs["prominence"] = prominence
    if distance is not None and distance >= 1:
        kwargs["distance"] = int(distance)
    indices, _props = _signal.find_peaks(y_arr, **kwargs)
    if indices.size == 0:
        warnings.append("Verilen parametrelerle belirgin bir pik bulunamadı.")
    return PeaksResult(indices=indices, x=x_arr[indices], y=y_arr[indices], warnings=warnings, params=dict(kwargs))
