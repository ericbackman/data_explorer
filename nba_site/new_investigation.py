#!/usr/bin/env python3
"""
new_investigation.py — Scaffold a new NBA Data Lab investigation.

Creates investigations/<slug>/index.html from a starter template and prints
a manifest entry to paste into investigations.js.

Usage:
    python nba_site/new_investigation.py <slug> "Investigation Title"
    python nba_site/new_investigation.py clutch-kings-2025 "Clutch Kings"
"""

import sys, os, datetime

HERE = os.path.dirname(os.path.abspath(__file__))

STARTER_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title} — NBA Data Lab</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <!-- <script src="data.js"></script>  <- uncomment once your data script writes data.js -->
  <style>
    :root {{
      --bg:#0f1117; --bg2:#1a1d27; --bg3:#242836;
      --text:#e4e6ed; --text2:#8b90a0; --accent:{accent}; --border:#2a2e3a;
      --mono:'JetBrains Mono','Fira Code',Consolas,monospace;
      --sans:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
    }}
    *,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
    body{{background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.65}}
    a{{color:var(--accent);text-decoration:none}}
    .backlink{{position:fixed;top:1.1rem;left:1.25rem;font-family:var(--mono);font-size:.72rem;color:var(--text2);background:rgba(15,17,23,.7);backdrop-filter:blur(8px);border:1px solid var(--border);border-radius:100px;padding:.4rem .85rem}}
    .backlink:hover{{color:var(--accent);border-color:var(--accent)}}
    .hero{{min-height:60vh;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:2rem}}
    .hero__eyebrow{{font-family:var(--mono);font-size:.72rem;color:var(--accent);letter-spacing:.16em;text-transform:uppercase;margin-bottom:1rem}}
    .hero__title{{font-size:clamp(2.2rem,7vw,4rem);font-weight:800;line-height:1.05;letter-spacing:-.03em}}
    .section{{max-width:1100px;margin:0 auto;padding:4rem 2rem}}
    .section__tag{{font-family:var(--mono);font-size:.72rem;color:var(--accent);letter-spacing:.16em;text-transform:uppercase;margin-bottom:.5rem}}
    .section__title{{font-size:clamp(1.6rem,4vw,2.2rem);font-weight:700;margin-bottom:1rem}}
    .placeholder{{background:var(--bg2);border:1px dashed var(--border);border-radius:12px;padding:2rem;color:var(--text2);font-family:var(--mono);font-size:.85rem}}
    footer{{text-align:center;padding:2rem;font-family:var(--mono);font-size:.7rem;color:#3a3e4a;border-top:1px solid var(--border)}}
  </style>
</head>
<body>
<a class="backlink" href="../../">← NBA Data Lab</a>

<section class="hero">
  <p class="hero__eyebrow">NBA Analytics Brief</p>
  <h1 class="hero__title">{title}</h1>
</section>

<div class="section">
  <p class="section__tag">01 / The Question</p>
  <h2 class="section__title">What are we investigating?</h2>
  <div class="placeholder">
    Scaffold ready. Build your data script to emit <code>data.js</code>
    (pattern: <code>const {const_name}_DATA = {{...}};</code>), then render it here
    with createElement/textContent. See ../mitchell-top10/index.html for a full example.
  </div>
</div>

<footer>NBA Data Lab · data sourced from NBA.com via nba_api</footer>

<script>
/* Render from window.{const_name}_DATA once data.js exists.
   Use createElement + textContent (not innerHTML) to stay consistent
   with the project's security conventions. */
</script>
</body>
</html>
"""

MANIFEST_SNIPPET = """  {{
    slug:        "{slug}",
    title:       "{title}",
    subtitle:    "TODO short kicker",
    description: "TODO one or two sentence summary of the finding.",
    date:        "{date}",
    tags:        ["TODO", "Category"],
    accent:      "{accent}",
    headline:    {{ stat: "TBD", label: "Key Stat" }},
    status:      "draft",
  }},"""


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    slug  = sys.argv[1].strip().lower().replace(" ", "-")
    title = sys.argv[2].strip()
    date  = datetime.date.today().isoformat()
    accent = "#4f8ff7"
    const_name = slug.upper().replace("-", "_")

    folder = os.path.join(HERE, "investigations", slug)
    if os.path.exists(folder):
        print(f"  [error] investigations/{slug}/ already exists — aborting.")
        sys.exit(1)

    os.makedirs(folder)
    with open(os.path.join(folder, "index.html"), "w", encoding="utf-8") as f:
        f.write(STARTER_HTML.format(
            title=title, accent=accent, const_name=const_name,
        ))

    print(f"\n  Created investigations/{slug}/index.html\n")
    print("  Paste this into investigations.js (inside the INVESTIGATIONS array):\n")
    print(MANIFEST_SNIPPET.format(slug=slug, title=title, date=date, accent=accent))
    print("\n  Then build a data script that writes "
          f"investigations/{slug}/data.js and flip status to \"live\".\n")


if __name__ == "__main__":
    main()
