"""
EVIDENCE SNAPSHOTS
------------------
For every check we save (1) an image of what the pricing page showed and (2) the raw page HTML.
The image is rendered from the page data we fetched, labelled with source URL and retrieval time.
"""
import os
import re
import time

from PIL import Image, ImageDraw, ImageFont

import db

PERIOD_TEXT = {"monthly": "per month", "yearly": "per year"}


def _font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size), True
        except OSError:
            continue
    return ImageFont.load_default(), False


def abs_path(rel):
    return os.path.join(db.DATA_DIR, rel) if rel else None


def render_snapshot(company, plans, evidence):
    folder = os.path.join(db.DATA_DIR, "evidence")
    os.makedirs(folder, exist_ok=True)
    base = f"{re.sub(r'[^a-z0-9]+', '', company.lower())}_{time.time_ns()}"
    if evidence.get("html"):
        with open(os.path.join(folder, base + ".html"), "w", encoding="utf-8") as f:
            f.write(evidence["html"])

    f_big, unicode_ok = _font(34)
    f_mid, _ = _font(22)
    f_small, _ = _font(15)

    def t(s):
        return s if unicode_ok else s.replace("₹", "Rs ")

    W, H = 960, 440
    img = Image.new("RGB", (W, H), "#f5f6fa")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 86], fill="#2d3a8c")
    d.text((30, 16), t(f"{company} - pricing page snapshot"), fill="white", font=f_mid)
    d.text((30, 54), t(f"{evidence['source_url']}  |  retrieved {evidence['retrieved_at']} UTC  |  HTTP {evidence['http_status']}"),
           fill="#cfd5ff", font=f_small)

    if not plans:
        d.text((30, 200), "No plans could be read from this page.", fill="#b33", font=f_mid)
    else:
        n = len(plans)
        card_w = (W - 60 - 20 * (n - 1)) // n
        for i, p in enumerate(plans):
            x = 30 + i * (card_w + 20)
            d.rounded_rectangle([x, 120, x + card_w, 360], radius=14, fill="white", outline="#d0d4e4")
            d.text((x + 20, 140), t(p["plan"]), fill="#222222", font=f_mid)
            ok = p["status"] == "ok"
            d.text((x + 20, 200), t(p["raw_price"]), fill="#2d3a8c" if ok else "#bb3333", font=f_big)
            sub = PERIOD_TEXT.get(p["period"], "") if ok else "no public price"
            d.text((x + 20, 265), sub, fill="#777777", font=f_small)
    d.text((30, 395), "Evidence image rendered from the fetched page data. Raw page HTML is saved alongside.",
           fill="#888888", font=f_small)

    img.save(os.path.join(folder, base + ".png"))
    return f"evidence/{base}.png"
