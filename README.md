# Scientific Graph Studio

A Tkinter-based desktop application for building publication-quality
scientific plots (line/XY, bar, error bars, dual-axis, fits) from
CSV/XLS/XLSX data.

## v7.2.0: Windows distribution

Windows 10/11 x64 installer and portable builds are produced by the tested
GitHub Actions workflow. See [Windows installation and build guide](WINDOWS.md)
and [release notes](RELEASE_NOTES.md). Python is not required on the end user's
computer. Download published installers from
[GitHub Releases](https://github.com/acanalkoc/grafiktasarim/releases).

Autosave now uses a per-user writable directory, and Windows image clipboard
copy supplies both PNG and DIB formats. Build dependencies are pinned separately
in `requirements-windows.txt`. Run all release tests with
`python scripts/test_release.py`; no skipped tests are accepted by the gate.

## v7.1: Usability and data-integrity audit

Single-agent audit with reproducible findings and remaining limitations:
[AUDIT_V71.md](AUDIT_V71.md). The visible data-table routes share one worksheet
editor (Actions menu, numeric-aware row sort, read-only non-destructive filter,
column properties, clipboard operations and undo). Export shortcuts, menu and
canvas use the same Publication dialog with actual rendered Output Preview.

Project writes are atomic; invalid pastes cannot truncate extra columns;
deleted XY/error source columns become stale rather than silently rebinding.
Analysis results go to their source worksheet, and changed sources mark stored
results stale. The error-bar editor uses source-column UUIDs and explicit
SD/SEM/CI meaning. See the audit for migration and missing-data limitations.

Run the suite below with `test_v71_audit` included (239 tests in the final
verified audit run). Screenshots are reproducible with `qa_capture_v71.py`.

## v7.0: Compact scientific figure workspace

The main window is now a document-first, three-pane shell:

- **Left** — a compact ~240 px **Workflow** column: Import Data (additive,
  multi-file/multi-sheet), Paste Table (Excel/Sheets clipboard, explicit
  header option), Plot Setup and Publication as the primary actions, an
  **Advanced ▾** menu for the legacy single-file loader/Layer Manager/Data
  Manager, and **Details** opening the legacy per-series editor in a
  separate scrollable window, keeping the figure workspace uncluttered.
- **Center** — the large white/paper graph page.
- **Right** — the single **Project Explorer** (the old duplicate tree
  inside the left sidebar notebook was removed).

**Plot Setup** (`gui/plot_setup.py`) is a modeless dialog: pick a
worksheet, an X column, one or more Y columns (by UUID, duplicate headers
disambiguated with their spreadsheet column letter), a target A–D panel and
a plot kind, then **Add** or **Replace Panel** (one undo step). Point-count
feedback previews how many valid rows each Y column contributes before
committing.

**Publication export** (`gui/publication.py` / `core/publication.py`)
enforces exact mm dimensions by default (tight-crop is opt-in and warns it
changes the physical size), a white/black "paper" look independent of the
active app theme, editable vector text in PDF/SVG, and validates finite
ranges plus a 40 MP raster cap. Every colour/size change made for export is
restored in a `finally` block even if the export raises. Nature (89/183 mm)
and general (90/180 mm) presets are labelled as illustrative examples, not a
journal-acceptance guarantee.

The advanced **Layer Manager** and single-file loader remain available
under the Workflow panel's Advanced menu / File menu for anyone who prefers
the v6.x flow.

## v6.0: Origin-like scientific workspace

The application now starts in the **Origin Bilimsel Açık** theme by default —
a light gray application shell, white content surfaces, dark readable text, a
measured scientific-blue accent, and distinct panel borders, without copying
OriginLab's branding or assets. The main window is a three-pane workspace:

- **Left** — the compact Quick Settings tab for data and plot selection.
- **Center** — the gray workspace with the white graph page/canvas.
- **Right** — a persistent, dockable **Project/Object Manager**, shown or
  hidden from **View → Object Manager (Right Panel)**.

A compact top toolbar (Open Data, Table, Line/Scatter/Column quick type
selectors, Rescale, Layers, Fit, Annotate, Properties) sits above the
workspace, and new **Plot** and **Format** main menus route to plot type,
rescale, layer, axis, legend, drawing and property windows without removing
any existing command.

Above the preview, a context-sensitive **Mini Toolbar** shows the current
selection (Page / Layer / Plot / Axis / Legend / Annotation) with quick
Show/Hide, Rescale and Properties actions. Selecting an object in the Object
Manager, on the canvas, or via the right-click menu updates the same shared
selection state, and the canvas context menu shows the selected object above
a **Properties…** command that opens the shared **Plot Details / Grafik
Özellikleri** window — single-instanced, opened on the current selection,
with a project graph tree on the left and **Quick / View / Object** tabs on
the right that route to the existing layer, axis, legend and annotation
editors.

## Progressive workspace (v5.9 foundation)

Daily controls stay in the **Quick Settings** tab, while **Project &
Objects** exposes a persistent Project → Workbook → Worksheet and
Graph → Layer → Plot hierarchy. Double-click an object to open its relevant
detailed editor; plots can be shown or hidden directly from the Object
Manager.

Column settings now preserve stable column identities, units, comments, data
types, missing-value policies, and extended scientific roles. Graph layers and
data-free appearance templates persist with the project and are managed from
**View → Layer Manager** and **View → Graph Templates**.

Line/XY graphs support persisted main and inset layers with normalized canvas
coordinates, layer visibility, per-layer plot assignment, and linked X/Y axes.
These controls remain behind the Layer Manager so the default workspace stays
compact.

Layer Manager also provides inset, horizontal, vertical, and grid auto-layouts.
Each layer can override its title, X/Y labels, linear/log scales, ranges, and
legend visibility through a separate Axis Details window.

Preview actions are consolidated in the canvas context menu: right-click
anywhere in the preview to undo/redo, open the table, export, copy, annotate,
or open detailed graph controls. The Quick Settings header keeps only data
loading and table access.

All legend, error-bar, annotation, axis, and grid controls now live in the
preview context menu. The Drawing & Annotation Studio combines quick insertion
with a persistent object list, content/position, style, visibility, locking,
rotation, duplication, and graph-layer assignment.

## Prerequisites

- Python 3.10+ with a **Tk-enabled** interpreter (the GUI is built on
  `tkinter`). On macOS, the python.org / Framework builds and Homebrew's
  `python-tk` package include Tk; some minimal/portable Python builds do
  not — if `import tkinter` fails, install a Tk-enabled Python instead.
- The packages listed in `requirements.txt` (NumPy, Matplotlib, pandas,
  openpyxl, xlrd, SciPy).

## Setup (portable virtual environment)

From the project root:

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
python -m pip install -r requirements.txt
```

Verify Tk is available in the interpreter you'll use:

```bash
python -c "import tkinter; print('tkinter OK')"
```

## Running the application

```bash
python app_main.py
```

## Running the test suite

The authoritative test suite is `test_suite.py`, run via `unittest`:

```bash
python -m unittest -v test_suite
```

## Regenerating the error-bar showcase images

Regenerates the four representative error-bar PNGs under `sample_outputs/`:

```bash
python test_error_bar_plots.py
```

## Generating all sample plots (optional)

Regenerates the full set of sample plots under `sample_outputs/` from the
bundled test datasets:

```bash
python generate_sample_plots.py
```
