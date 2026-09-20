import matplotlib
import matplotlib.axes
from matplotlib.ticker import AutoMinorLocator, MultipleLocator
from typing import Optional

def bilimsel_stil_uygula(
    ax: matplotlib.axes.Axes,
    yazi_boyutu: int = 11,
    cizgi_kalinligi: float = 1.15,
    major_grid: bool = False,
    minor_grid_x: bool = False,
    minor_grid_y: bool = False,
    top_spine: bool = True,
    right_spine: bool = True,
    left_spine: bool = True,
    bottom_spine: bool = True,
    top_ticks: bool = True,
    right_ticks: bool = True,
    left_ticks: bool = True,
    bottom_ticks: bool = True,
    remove_top_right_minor: bool = False,
    fg_color: str = "#0F172A",
    grid_color: str = "#CBD5E1",
) -> None:
    """Tüm 4 eksene içe bakan çentikler, eksen çizgileri ve bağımsız ızgara kontrolü uygular."""
    ax.tick_params(
        direction="in",
        which="major",
        length=6.0,
        width=cizgi_kalinligi,
        colors=fg_color,
        top=top_ticks,
        right=right_ticks,
        bottom=bottom_ticks,
        left=left_ticks,
        labelsize=yazi_boyutu,
    )
    ax.tick_params(
        direction="in",
        which="minor",
        length=3.5,
        width=max(0.7, cizgi_kalinligi * 0.75),
        colors=fg_color,
        top=top_ticks and not remove_top_right_minor,
        right=right_ticks and not remove_top_right_minor,
        bottom=bottom_ticks,
        left=left_ticks,
    )

    for spine_name, spine in ax.spines.items():
        spine.set_linewidth(cizgi_kalinligi)
        spine.set_color(fg_color)
        if spine_name == "top":
            spine.set_visible(top_spine)
        elif spine_name == "right":
            spine.set_visible(right_spine)
        elif spine_name == "left":
            spine.set_visible(left_spine)
        elif spine_name == "bottom":
            spine.set_visible(bottom_spine)

    if not isinstance(ax.xaxis.get_scale(), str) or ax.xaxis.get_scale() == "linear":
        ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    if not isinstance(ax.yaxis.get_scale(), str) or ax.yaxis.get_scale() == "linear":
        ax.yaxis.set_minor_locator(AutoMinorLocator(2))

    if major_grid:
        ax.grid(True, which="major", color=grid_color, linestyle="--", linewidth=0.75, alpha=0.6, zorder=0)
    else:
        ax.grid(False, which="major")

    if minor_grid_x:
        ax.grid(True, which="minor", axis="x", color=grid_color, linestyle=":", linewidth=0.5, alpha=0.4, zorder=0)
    if minor_grid_y:
        ax.grid(True, which="minor", axis="y", color=grid_color, linestyle=":", linewidth=0.5, alpha=0.4, zorder=0)


def etiketleri_bicimlendir(ax: matplotlib.axes.Axes, title: str, xlabel: str, ylabel: str, font_size: int = 11, fg_color: str = "#0F172A") -> None:
    if title:
        ax.set_title(title, fontsize=font_size + 2, fontweight="bold", pad=10, color=fg_color)
    if xlabel:
        ax.set_xlabel(xlabel, fontsize=font_size + 1, fontweight="normal", labelpad=7, color=fg_color)
    if ylabel:
        ax.set_ylabel(ylabel, fontsize=font_size + 1, fontweight="normal", labelpad=7, color=fg_color)


def eksen_limitlerini_ayarla(
    ax: matplotlib.axes.Axes,
    y_min: Optional[float] = None,
    y_max: Optional[float] = None,
    y_step: Optional[float] = None,
    x_min: Optional[float] = None,
    x_max: Optional[float] = None,
    x_step: Optional[float] = None,
) -> None:
    if y_min is not None or y_max is not None:
        lo, hi = ax.get_ylim()
        ax.set_ylim(y_min if y_min is not None else lo, y_max if y_max is not None else hi)
    if y_step is not None and y_step > 0:
        ax.yaxis.set_major_locator(MultipleLocator(y_step))

    if x_min is not None or x_max is not None:
        lo, hi = ax.get_xlim()
        ax.set_xlim(x_min if x_min is not None else lo, x_max if x_max is not None else hi)
    if x_step is not None and x_step > 0:
        ax.xaxis.set_major_locator(MultipleLocator(x_step))
