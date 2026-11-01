"""Copy every saved business and built site from this PC to the hosted builder.

    python copy_to_render.py      (or double-click "Copy to Render.bat")

Asks for the Render link and BUILDER_PASSWORD (typed hidden), then uploads.
Businesses with the same name on Render are replaced by this PC's copy.
"""
import base64
import getpass
import json
import urllib.error
import urllib.request

import app


def main():
    url = input("Render link (e.g. https://site-builder-xxxx.onrender.com): ").strip().rstrip("/")
    if not url.startswith("https://"):
        url = "https://" + url.removeprefix("http://")
    pw = getpass.getpass("BUILDER_PASSWORD (hidden as you type): ")
    data = app.export_zip()
    print(f"Uploading {len(data) / 1_048_576:.1f} MB...")
    req = urllib.request.Request(f"{url}/api/import", data=data, method="POST", headers={
        "Content-Type": "application/zip",
        "Authorization": "Basic " + base64.b64encode(f"landon:{pw}".encode()).decode()})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            res = json.load(r)
    except urllib.error.HTTPError as e:
        print("Wrong password." if e.code == 401 else f"Upload failed: HTTP {e.code} {e.read()[:200]!r}")
        return
    if res.get("ok"):
        print("Copied:", ", ".join(res["imported"]))
        print(f"Open {url} on your phone to see them.")
    else:
        print("Upload failed:", res.get("error"))


if __name__ == "__main__":
    main()
