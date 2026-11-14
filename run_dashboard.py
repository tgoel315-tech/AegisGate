"""
AegisGate Master Launch Script
Starts the backend and opens the real-time SOC dashboard in your default browser.
"""

import os
import sys
import webbrowser
import time
import subprocess
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = ROOT_DIR / "backend"

def main():
    print("=" * 65)
    print("  AEGISGATE :: AI-POWERED SMART ENTRY & TAILGATING MONITOR")
    print("=" * 65)
    print("\n[STARTING] Initializing SOC Backend on http://localhost:8000 ...")

    # Open browser after a brief delay
    def open_browser():
        time.sleep(1.2)
        print("[LAUNCH] Opening dashboard in browser: http://localhost:8000")
        webbrowser.open("http://localhost:8000")

    import threading
    t = threading.Thread(target=open_browser, daemon=True)
    t.start()

    os.chdir(str(BACKEND_DIR))
    subprocess.run([sys.executable, "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--reload"])

if __name__ == "__main__":
    main()
