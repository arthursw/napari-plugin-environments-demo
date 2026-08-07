# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = [
#   "napari[optional,pyqt6]",
#   "napari-isolation-demo",
#   "napari-plugin-manager",
#   "npe2",
#   "wetlands==2.3.3",
# ]
# [tool.uv]
# override-dependencies = ["npe2>=0.8.4.dev0"]
# [tool.uv.sources]
# napari = { path = "../napari/.worktrees/plugin-environments", editable = true }
# napari-isolation-demo = { path = "plugins/napari-isolation-demo" }
# napari-plugin-manager = { path = "../napari-plugin-manager/.worktrees/plugin-environments", editable = true }
# npe2 = { path = "../napari/.worktrees/npe2-plugin-environments", editable = true }
# wetlands = { path = "../wetlands", editable = true }
# ///

from pathlib import Path
from runpy import run_path

run_path(Path(__file__).with_name('smoke.py'), run_name='__main__')
