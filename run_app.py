"""
Quran SRT Sync - Application Launcher
Starts FastAPI web server and opens the browser.
"""

import sys
import os
import webbrowser
import threading
import time

def open_browser():
    time.sleep(1.5)
    print("Opening web browser at http://127.0.0.1:8000 ...")
    webbrowser.open("http://127.0.0.1:8000")

if __name__ == '__main__':
    # Ensure UTF-8 output
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    threading.Thread(target=open_browser, daemon=True).start()

    import uvicorn
    print("=================================================================")
    print("          Starting Quran SRT Sync Web Server...                  ")
    print("          URL: http://127.0.0.1:8000                            ")
    print("          Press Ctrl+C to stop.                                  ")
    print("=================================================================")
    loop = "asyncio:SelectorEventLoop" if sys.platform == "win32" else "auto"
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False, loop=loop)
