#!/usr/bin/env python3
"""
deploy.py — Publish nba_site/ to the public GitHub Pages repo.

Mirrors this folder's contents into ericbackman/nba-data-lab and pushes,
which triggers a GitHub Pages rebuild. The data_explorer repo stays private;
only nba_site/ content is published.

Usage:
    python nba_site/deploy.py
    python nba_site/deploy.py -m "add clutch-kings investigation"

Live site: https://ericbackman.github.io/nba-data-lab/
"""

import os, sys, shutil, subprocess, tempfile, datetime

HERE        = os.path.dirname(os.path.abspath(__file__))
REPO_URL    = "https://github.com/ericbackman/nba-data-lab.git"
EXCLUDE     = {".cache.json", ".git", "__pycache__"}  # never publish these


def run(cmd, cwd=None):
    """Run a command, streaming output; raise on failure."""
    print(f"  $ {' '.join(cmd)}")
    subprocess.run(cmd, cwd=cwd, check=True)


def mirror_into(dest):
    """Copy nba_site/ contents into dest, skipping EXCLUDE and cache files."""
    # Clear dest's tracked files (keep .git)
    for entry in os.listdir(dest):
        if entry == ".git":
            continue
        path = os.path.join(dest, entry)
        shutil.rmtree(path) if os.path.isdir(path) else os.remove(path)

    # Copy fresh from nba_site/
    def _ignore(_dir, names):
        return [n for n in names if n in EXCLUDE or n.endswith(".cache.json")]

    for entry in os.listdir(HERE):
        if entry in EXCLUDE:
            continue
        src = os.path.join(HERE, entry)
        dst = os.path.join(dest, entry)
        if os.path.isdir(src):
            shutil.copytree(src, dst, ignore=_ignore)
        else:
            shutil.copy2(src, dst)

    # Always ship a .gitignore so cache files can never be published by hand
    with open(os.path.join(dest, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(".cache.json\n*.cache.json\n.DS_Store\nThumbs.db\n")


def main():
    msg = "deploy: update NBA Data Lab"
    if "-m" in sys.argv:
        i = sys.argv.index("-m")
        if i + 1 < len(sys.argv):
            msg = sys.argv[i + 1]
    msg += f" ({datetime.date.today().isoformat()})"

    with tempfile.TemporaryDirectory() as tmp:
        clone = os.path.join(tmp, "site")
        print("\nDeploying nba_site/ -> nba-data-lab ...\n")
        run(["git", "clone", "--depth", "1", REPO_URL, clone])

        mirror_into(clone)

        run(["git", "add", "-A"], cwd=clone)

        # Skip the commit if nothing changed
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=clone,
            capture_output=True, text=True,
        ).stdout.strip()
        if not status:
            print("\n  No changes to deploy — site already up to date.\n")
            return

        run(["git", "commit", "-m", msg], cwd=clone)
        run(["git", "push", "origin", "main"], cwd=clone)

    print("\n  Deployed. Pages will rebuild in ~1 min:")
    print("  https://ericbackman.github.io/nba-data-lab/\n")


if __name__ == "__main__":
    main()
