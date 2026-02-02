import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
mw_path = ROOT / "ui" / "main_window.py"
if not mw_path.exists():
    raise SystemExit(f"Cannot find {mw_path}. Run this script from the project root (folder containing ui/).")

txt = mw_path.read_text(encoding="utf-8", errors="ignore")

# 1) Ensure Slot is imported from PySide6.QtCore
m = re.search(r"from\s+PySide6\.QtCore\s+import\s+([^\n]+)", txt)
if m:
    imports = m.group(1)
    if "Slot" not in imports:
        new_imports = imports.strip()
        # append Slot with comma separation
        if new_imports.endswith(","):
            new_imports = new_imports + " Slot"
        else:
            new_imports = new_imports + ", Slot"
        txt = txt[:m.start(1)] + new_imports + txt[m.end(1):]
else:
    # Fallback: add a new import near the top (after PySide6 imports if present)
    lines = txt.splitlines()
    insert_at = 0
    for i, line in enumerate(lines[:80]):
        if line.startswith("from PySide6") or line.startswith("import PySide6"):
            insert_at = i + 1
    lines.insert(insert_at, "from PySide6.QtCore import Slot")
    txt = "\n".join(lines) + ("\n" if not txt.endswith("\n") else "")

# 2) Replace progress connect to use a real slot (no lambda)
txt = re.sub(r"self\._worker\.progress\.connect\([^\)]*\)",
             "self._worker.progress.connect(self._on_progress)",
             txt)

# 3) Ensure _on_progress exists inside MainWindow class with correct indentation
if "def _on_progress" not in txt:
    # Insert after _set_status if possible, else after __init__
    insert_block = "\n    @Slot(int, str)\n    def _on_progress(self, pct: int, msg: str):\n        # UI-thread safe progress update\n        self._set_status(msg, pct)\n"
    if "def _set_status" in txt:
        # insert before next def after _set_status
        idx = txt.find("def _set_status")
        next_def = txt.find("\n    def ", idx + 1)
        if next_def != -1:
            txt = txt[:next_def] + insert_block + "\n" + txt[next_def:]
        else:
            txt = txt + "\n" + insert_block + "\n"
    else:
        idx = txt.find("def __init__")
        next_def = txt.find("\n    def ", idx + 1) if idx != -1 else -1
        if next_def != -1:
            txt = txt[:next_def] + insert_block + "\n" + txt[next_def:]
        else:
            # last resort: append inside class by finding class line and appending at end (may not be perfect if class ends earlier)
            txt = txt + "\n" + insert_block + "\n"

mw_path.write_text(txt, encoding="utf-8")
print("Patched ui/main_window.py successfully.")
