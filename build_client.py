"""Rebuild one saved business from the command line (same as clicking Build in the app).

    python build_client.py bonsai-green-cleaning [--no-ai] [--rewrite]
"""
import json
import sys

import app
from sitebuilder.generator import build_site


def main():
    slug = sys.argv[1]
    app.load_env()
    cdir = app.CLIENTS / slug
    data = json.loads((cdir / "input.json").read_text(encoding="utf-8"))
    pdir = cdir / "photos"
    res = build_site(data, app.SITES / slug,
                     logo=(cdir / "logo.png") if (cdir / "logo.png").exists() else None,
                     hero=(cdir / "hero.jpg") if (cdir / "hero.jpg").exists() else None,
                     svc_photos={f.stem[4:]: f for f in pdir.glob("svc-*.img")},
                     gallery=sorted(pdir.glob("gal-*.img")),
                     use_ai="--no-ai" not in sys.argv, rewrite_copy="--rewrite" in sys.argv,
                     **{k: cdir / f"{k}.jpg" for k in ("about", "before", "after") if (cdir / f"{k}.jpg").exists()})
    print(f"Built {res['pages']} pages. Stock: {', '.join(res['stock']) or 'none'}. No photo: {', '.join(res['no_photo']) or 'none'}")


if __name__ == "__main__":
    main()
