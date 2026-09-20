"""Single release test entry point; fails if any regression test is skipped."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
MODULES = ["test_v63_panels", "test_v62_workspace", "test_suite",
           "test_analysis_studio", "test_error_bar_plots", "test_v70_workflow",
           "test_v71_audit", "test_v72_release"]

if __name__ == "__main__":
    suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    for test, detail in result.failures + result.errors:
        # Surface concrete test errors in Actions annotations, not just exit 1.
        text = (str(test) + "\n" + detail).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error::" + text, flush=True)
    for test, reason in result.skipped:
        print("::error::Release gate rejects skipped test: " + str(test) + " " + reason, flush=True)
    raise SystemExit(0 if result.wasSuccessful() and not result.skipped else 1)
