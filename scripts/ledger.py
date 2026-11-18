#!/usr/bin/env python3
"""Deployment ledger: repo -> Cloudflare project -> URL -> channel.

Pure stdlib. Keeps one JSON file next to this script (../state/deployments.json)
so the skill stays self-contained instead of appending to a global memory file.

Usage:
  python3 ledger.py --add --repo <url-or-path> --project <cf_name> \
      --url <prod-url> --channel A [--type vite-static] [--preview <url>] \
      [--note "..."]

  python3 ledger.py --list          # table of all records
  python3 ledger.py --get <repo>    # JSON for one repo (exit 1 if unknown)
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

STATE = Path(__file__).resolve().parent.parent / "state" / "deployments.json"


def load():
    if not STATE.is_file():
        return {"deployments": []}
    try:
        data = json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"deployments": []}
    if not isinstance(data, dict) or "deployments" not in data:
        return {"deployments": []}
    return data


def save(data):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                     encoding="utf-8")


def key_of(repo):
    k = repo.strip().lower()
    for p in ("https://", "http://", "git@"):
        if k.startswith(p):
            k = k[len(p):]
    k = k.rstrip("/")
    if k.endswith(".git"):
        k = k[:-4]
    if k.startswith("github.com:"):        # git@github.com:owner/repo
        k = "github.com/" + k.split(":", 1)[1]
    return k


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--get")
    ap.add_argument("--repo")
    ap.add_argument("--project")
    ap.add_argument("--url")
    ap.add_argument("--channel")
    ap.add_argument("--type")
    ap.add_argument("--preview")
    ap.add_argument("--note")
    a = ap.parse_args()

    data = load()

    if a.list or (not a.add and not a.get):
        rows = data.get("deployments", [])
        if not rows:
            print("(empty ledger)")
            return 0
        for r in rows:
            print(f"{r.get('project','?'):<28} {r.get('channel','?'):<8} "
                  f"{r.get('url','?'):<45} {r.get('repo','?')}")
        return 0

    if a.get:
        k = key_of(a.get)
        for r in data["deployments"]:
            if key_of(r.get("repo", "")) == k:
                print(json.dumps(r, ensure_ascii=False, indent=2))
                return 0
        print(f"not found: {a.get}", file=sys.stderr)
        return 1

    missing = [n for n in ("repo", "project", "url") if not getattr(a, n)]
    if missing:
        print("missing: " + ", ".join("--" + m for m in missing),
              file=sys.stderr)
        return 2

    rec = {
        "repo": a.repo,
        "project": a.project,
        "url": a.url,
        "channel": a.channel or "?",
        "type": a.type or "?",
        "preview": a.preview,
        "note": a.note,
        "updated_at": datetime.datetime.now().astimezone().isoformat(
            timespec="seconds"),
    }
    k = key_of(a.repo)
    for i, r in enumerate(data["deployments"]):
        if key_of(r.get("repo", "")) == k:
            rec["created_at"] = r.get("created_at", rec["updated_at"])
            data["deployments"][i] = rec
            break
    else:
        rec["created_at"] = rec["updated_at"]
        data["deployments"].append(rec)
    save(data)
    print(f"recorded: {rec['project']} -> {rec['url']} ({STATE})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
