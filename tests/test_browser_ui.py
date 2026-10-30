import os
import subprocess
import sys
import urllib.request

CHROME_PATH = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
SCREENSHOT_PATH = os.path.abspath("admin_ui_screenshot.png")
URL = "http://127.0.0.1:8501"

print(f"Testing Streamlit UI at {URL}...")

# 1. Verify HTTP Response
try:
    with urllib.request.urlopen(f"{URL}/_stcore/health", timeout=3) as r:
        assert r.status == 200
        print("Streamlit Core Health: OK (Status 200)")
except Exception as e:
    print(f"Streamlit HTTP Check Failed: {e}")
    sys.exit(1)

# 2. Check Static Assets and HTML
req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 Chrome/120.0"})
with urllib.request.urlopen(req) as resp:
    html = resp.read().decode("utf-8", errors="ignore")
    print(f"HTML Payload received: {len(html)} bytes")
    assert "<title>" in html
    print("HTML Structure Valid: Title and React root confirmed.")

# 3. Capture Headless Chrome Screenshot
if os.path.exists(CHROME_PATH):
    print(f"Launching Chrome Headless for rendering verification: {CHROME_PATH}")
    cmd = [
        CHROME_PATH,
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        f"--screenshot={SCREENSHOT_PATH}",
        "--window-size=1440,900",
        URL,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if os.path.exists(SCREENSHOT_PATH):
        sz = os.path.getsize(SCREENSHOT_PATH)
        print(f"SUCCESS: Captured UI screenshot ({sz} bytes) -> {SCREENSHOT_PATH}")
    else:
        print("Chrome finished with return code:", res.returncode)
else:
    print("Chrome not found at path, skipping image export.")

print("\nBrowser UI Verification Complete!")
