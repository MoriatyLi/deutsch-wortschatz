# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys
from PyInstaller.utils.hooks import copy_metadata, collect_data_files, collect_submodules

root = Path(SPECPATH)
sys.path.insert(0, str(root))
from tools.build_seed import prepare_seed

seed = root / "build" / "desktop-seed" / "vocab.db"
include_personal = os.environ.get("DEUTSCH_VOCAB_INCLUDE_PERSONAL_DATA") == "1"
prepare_seed(seed, root / "data" / "vocab.db", include_personal=include_personal)
resources = [
    (str(root / name), "app_resources")
    for name in ("app.py", "vocab.py", "providers.py", "lexicon.py",
                 "offline_dictionary.py", "prepare_offline.py", "obsidian.py",
                 "export_obsidian.py")
]
resources += [
    (str(root / ".streamlit" / "config.toml"), "app_resources/.streamlit"),
    (str(root / "data" / "dictionaries" / "de-zh.db"), "app_resources/dictionary"),
    (str(seed), "app_resources/user_data"),
]
resources += [(str(path), "app_resources/user_data/audio")
              for path in (root / "data" / "audio").glob("*") if include_personal and path.is_file()]
resources += copy_metadata("streamlit")
resources += collect_data_files("streamlit")

a = Analysis(
    [str(root / "desktop_app.py")], pathex=[str(root)], binaries=[], datas=resources,
    hiddenimports=collect_submodules("streamlit", filter=lambda name: not name.startswith(("streamlit.testing", "streamlit.hello"))) +
                  ["webview", "webview.platforms.edgechromium", "webview.platforms.winforms",
                   "clr", "clr_loader", "pythonnet", "bottle", "proxy_tools",
                   "providers", "lexicon", "offline_dictionary", "prepare_offline",
                   "obsidian", "export_obsidian"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=["pytest", "tkinter"],
    noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="DeutschWortschatz",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
          console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name="DeutschWortschatz")
