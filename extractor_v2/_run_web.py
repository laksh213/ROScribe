"""Web-mode launcher for local preview of the V2 app (native=False)."""
import sys, os
from pathlib import Path
ROOT = Path("/Users/laksh/Desktop/ROScribe")
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
import extractor_v2.app as v2  # registers @ui.page("/"); does NOT call main()
from nicegui import ui
ui.run(native=False, host="127.0.0.1", port=8090, reload=False, show=False,
       title="ROS Extractor System (web preview)")
