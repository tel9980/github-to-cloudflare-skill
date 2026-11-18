#!/usr/bin/env python3
"""Analyze a GitHub project / local dir and emit a Cloudflare deploy plan (JSON).

Offline only: clones (if given a URL) + inspects files. Never contacts
Cloudflare, never deploys, never runs project build scripts.

Usage:
  python3 analyze.py <repo-url-or-local-path> [--branch B] [--workdir DIR] [--out plan.json]

Private HTTPS repos: export GITHUB_TOKEN=<gh token with repo read>; it is
injected into the clone URL and redacted from all output.
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def redact(text, token):
    return text.replace(token, "***REDACTED***") if token else text


def parse_repo(url):
    """Return (owner, name) for github URLs, else (None, name)."""
    m = re.search(r"github\.com[:/]([^/]+)/([^/#?]+?)(?:\.git)?(?:[/#?].*)?$", url)
    if m:
        return m.group(1), m.group(2)
    return None, Path(url.rstrip("/")).name


def sanitize_name(name):
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)[:50].strip("-")
    return s or "cf-app"


def clone(url, workdir, branch, token):
    owner, name = parse_repo(url)
    dest = Path(workdir) / f"{owner or 'local'}__{name}"
    if dest.exists():
        fetch = ["git"]
        if token and (dest / ".git").exists():
            fetch += ["-c", "http.https://github.com/.extraheader="
                      f"Authorization: Bearer {token}"]
        fetch += ["-C", str(dest), "fetch", "--depth", "1"]
        subprocess.run(fetch, capture_output=True, text=True)
    else:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        u = url
        cmd = ["git"]
        if token and u.startswith("https://github.com"):
            # Auth via a per-command header only. Rewriting the remote URL
            # would persist the token in .git/config on disk.
            cmd += ["-c", "http.https://github.com/.extraheader="
                    f"Authorization: Bearer {token}"]
        cmd += ["clone", "--depth", "1"]
        if branch:
            cmd += ["--branch", branch]
        cmd += [u, str(dest)]
        p = run(cmd)
        if p.returncode != 0:
            sys.exit("clone failed: " + redact(p.stderr.strip(), token))
    if branch:
        run(["git", "-C", str(dest), "checkout", branch])
    head = run(["git", "-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"])
    default_branch = head.stdout.strip() or (branch or "main")
    return dest, default_branch


def load_pkg(root):
    pj = root / "package.json"
    if not pj.is_file():
        return None
    try:
        return json.loads(pj.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def deps_of(pkg):
    if not pkg:
        return {}
    return {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}


def read_any(root, patterns):
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    return ""
    return None


def has_dir(root, *names):
    return any((root / n).is_dir() for n in names)


def detect_one(root, rel=".", extra_signals=None):
    """Detect a single package dir. Returns dict fragment (no clone info)."""
    pkg = load_pkg(root)
    deps = deps_of(pkg)
    signals = list(extra_signals or [])
    plan = {
        "root_dir": rel,
        "install_command": "npm install" if pkg else "none (no package.json)",
        "build_command": None,
        "output_dir": None,
        "type": "unknown",
        "channel": "ask-user",
        "alternatives": [],
        "preconditions": [],
        "env_vars": {},
        # Same list object: every signals.append() below lands in the output.
        "signals": signals,
    }
    node_eng = (pkg or {}).get("engines", {}).get("node") if pkg else None

    wrangler_cfg = None
    for n in ("wrangler.jsonc", "wrangler.toml", "wrangler.json"):
        if (root / n).is_file():
            wrangler_cfg = n
            break
    if wrangler_cfg:
        signals.append(f"config:{wrangler_cfg}")
        cfg = read_any(root, [wrangler_cfg]) or ""
        main_m = re.search(r"""["']?main["']?\s*[:=]\s*["']([^"']+)["']""", cfg)
        assets_m = re.search(r'directory"?\s*[:=]\s*"([^"]+)"', cfg) or \
            re.search(r"directory\"?\s*[:=]\s*'([^']+)'", cfg)
        plan.update({
            "type": "worker",
            "channel": "workers-assets",
            "alternatives": ["pages-git if purely static output"],
            "build_command": ((pkg or {}).get("scripts", {})
                              .get("build") and "npm run build" or None),
            "output_dir": assets_m.group(1) if assets_m else None,
            "preconditions": [f"entry point per {wrangler_cfg}: "
                              + (main_m.group(1) if main_m else "(check file)")],
        })
        if "nodejs" in cfg:
            signals.append("config:nodejs_compat")
        return plan, node_eng

    if "next" in deps:
        nextcfg = read_any(root, ["next.config.js", "next.config.mjs",
                                  "next.config.ts"]) or ""
        static_export = re.search(r"""output\s*[:=]\s*["']export["']""", nextcfg)
        if "@opennextjs/cloudflare" in deps:
            plan.update({"type": "nextjs-opennext", "channel": "workers-assets",
                         "build_command": "npm run build && npx --yes "
                         "@opennextjs/cloudflare build",
                         "preconditions": ["deploy via "
                         "`npx --yes wrangler deploy` after build",
                         "ISR needs KV/R2 incremental cache in "
                         "open-next.config.ts"]})
        elif "@cloudflare/next-on-pages" in deps:
            plan.update({
                "type": "nextjs-on-pages", "channel": "workers-assets",
                "alternatives": ["pages-git (static export)"],
                "preconditions": [
                    "DEPRECATED adapter @cloudflare/next-on-pages detected: "
                    "remove it (and setupDevPlatform() calls) before "
                    "installing @opennextjs/cloudflare - they conflict",
                    "migrate: npm rm @cloudflare/next-on-pages && "
                    "npm i -D @opennextjs/cloudflare wrangler"]})
        elif static_export:
            plan.update({"type": "nextjs-static-export", "channel": "pages-git",
                         "build_command": "npm run build", "output_dir": "out",
                         "preconditions": ["static export needs no adapter; "
                         "do NOT add OpenNext (output:export is incompatible)"]})
        else:
            plan.update({
                "type": "nextjs-plain", "channel": "workers-assets",
                "alternatives": ["pages-git + add output:export if fully "
                                 "static site"],
                "build_command": "npm run build && npx --yes "
                "@opennextjs/cloudflare build",
                "preconditions": [
                    "add CF adapter: npm i -D @opennextjs/cloudflare "
                    "wrangler@latest",
                    "create open-next.config.ts "
                    "(defineCloudflareConfig, R2/KV cache for ISR)",
                    "create wrangler.jsonc with nodejs_compat flag and a "
                    "compatibility_date",
                    "or run `npx @opennextjs/cloudflare@latest deploy` "
                    "which scaffolds config and deploys"]})
        signals.append("dep:next")
        return plan, node_eng

    if "astro" in deps:
        cfg = read_any(root, ["astro.config.mjs", "astro.config.ts",
                              "astro.config.js", "astro.config.cjs"]) or ""
        if "@astrojs/cloudflare" in cfg or re.search(
                r"""output\s*:\s*["'](server|hybrid)["']""", cfg):
            plan.update({"type": "astro-cloudflare-ssr",
                         "channel": "workers-assets",
                         "build_command": "npm run build",
                         "output_dir": "dist/_worker.js",
                         "alternatives": ["pages-git (same build)"],
                         "preconditions": ["output:'hybrid' is deprecated in "
                         "Astro >=5; migrate to prerender"]})
        else:
            plan.update({"type": "astro-static", "channel": "pages-git",
                         "build_command": "npm run build",
                         "output_dir": "dist",
                         "alternatives": ["workers-assets"]})
        signals.append("dep:astro")
        return plan, node_eng

    if "@sveltejs/kit" in deps:
        cfg = read_any(root, ["svelte.config.js", "svelte.config.ts"]) or ""
        if "adapter-cloudflare" in cfg:
            plan.update({"type": "sveltekit-cloudflare",
                         "channel": "workers-assets",
                         "build_command": "npm run build",
                         "output_dir": ".svelte-kit/cloudflare",
                         "alternatives": ["pages-git (same build output)"]})
        elif "adapter-static" in cfg or "adapter-auto" in cfg:
            plan.update({"type": "sveltekit-static", "channel": "pages-git",
                         "build_command": "npm run build",
                         "output_dir": "build",
                         "preconditions": ["adapter-auto falls back to "
                         "static only without prerender entries"]})
        else:
            plan.update({"type": "sveltekit-unknown-adapter",
                         "channel": "pages-git",
                         "build_command": "npm run build",
                         "output_dir": "build",
                         "preconditions": ["npm i -D "
                         "@sveltejs/adapter-cloudflare and switch the "
                         "adapter to it for SSR on CF"]})
        signals.append("dep:@sveltejs/kit")
        return plan, node_eng

    if "nuxt" in deps:
        cfg = read_any(root, ["nuxt.config.ts", "nuxt.config.js",
                              "nuxt.config.mjs"]) or ""
        preset = re.search(r"""preset\s*:\s*["'](cloudflare[^"']*)["']""", cfg)
        if preset:
            out = ("dist/_worker.js" if "module" in preset.group(1)
                   else "dist")
            plan.update({"type": f"nuxt-{preset.group(1)}",
                         "channel": ("workers-assets" if "module"
                                     in preset.group(1) else "pages-git"),
                         "build_command": "npm run build",
                         "output_dir": out})
        else:
            plan.update({"type": "nuxt", "channel": "pages-git",
                         "build_command": "npm run generate",
                         "output_dir": "dist",
                         "alternatives": ["nitro preset cloudflare-module "
                         "-> workers-assets for SSR"],
                         "preconditions": ["static build via `nuxt "
                         "generate`; for server routes add "
                         "nitro.config.preset='cloudflare-module'"]})
        signals.append("dep:nuxt")
        return plan, node_eng

    if "docusaurus" in deps:
        plan.update({"type": "docusaurus", "channel": "pages-git",
                     "build_command": "npm run build", "output_dir": "build"})
        signals.append("dep:docusaurus")
        return plan, node_eng
    if any(d.startswith("@vuepress") for d in deps) or "vuepress" in deps:
        sub = "docs/.vuepress/dist"
        plan.update({"type": "vuepress", "channel": "pages-git",
                     "build_command": "npx vuepress build docs",
                     "output_dir": sub})
        signals.append("dep:vuepress")
        return plan, node_eng
    if "gatsby" in deps:
        plan.update({"type": "gatsby", "channel": "pages-git",
                     "build_command": "npm run build", "output_dir": "public"})
        signals.append("dep:gatsby")
        return plan, node_eng
    if "@11ty/eleventy" in deps:
        plan.update({"type": "eleventy", "channel": "pages-git",
                     "build_command": "npx @11ty/eleventy",
                     "output_dir": "_site"})
        signals.append("dep:@11ty/eleventy")
        return plan, node_eng
    if "hexo" in deps:
        plan.update({"type": "hexo", "channel": "pages-git",
                     "build_command": "npx hexo generate",
                     "output_dir": "public"})
        signals.append("dep:hexo")
        return plan, node_eng
    if "vite" in deps or "vue" in deps or "react" in deps or "svelte" in deps:
        plan.update({"type": "vite-static", "channel": "pages-git",
                     "build_command": "npm run build", "output_dir": "dist",
                     "alternatives": ["workers-assets (same dist)"]})
        signals.append("dep:vite/react/vue/svelte")
        return plan, node_eng
    if pkg:
        plan.update({"type": "nodejs-no-framework", "channel": "ask-user",
                     "preconditions": ["inspect package.json scripts; no "
                     "known CF-compatible framework detected"]})
        return plan, node_eng

    # non-node stacks
    if read_any(root, ["hugo.toml", "hugo.yaml", "config.toml",
                       "config.yaml", "config.json"]) is not None \
            and has_dir(root, "content", "layouts", "archetypes"):
        plan.update({"type": "hugo", "channel": "pages-git",
                     "build_command": "hugo --minify", "output_dir": "public",
                     "preconditions": ["Pages build image ships hugo; for "
                     "direct upload build locally first"]})
        signals.append("file:hugo config")
        return plan, node_eng
    if (root / "_config.yml").is_file() and (
            (root / "Gemfile").is_file() or has_dir(root, "_posts")):
        plan.update({"type": "jekyll", "channel": "pages-git",
                     "build_command": "jekyll build", "output_dir": "_site",
                     "preconditions": ["Pages build image ships ruby/jekyll"]})
        signals.append("file:jekyll")
        return plan, node_eng
    if (root / "mkdocs.yml").is_file():
        plan.update({"type": "mkdocs", "channel": "pages-git",
                     "build_command": "pip install -r requirements.txt "
                     "2>/dev/null; mkdocs build", "output_dir": "site"})
        signals.append("file:mkdocs.yml")
        return plan, node_eng

    for cand in (".", "public", "dist", "build", "docs", "site"):
        d = root if cand == "." else root / cand
        if (d / "index.html").is_file():
            plan.update({"type": "static", "channel": "pages-git",
                         "build_command": "", "output_dir": cand,
                         "alternatives": ["workers-assets",
                                          "direct-upload"]})
            if cand == ".":
                plan["preconditions"] = [
                    "output dir is the repo root; if the repo also holds "
                    "sources, move the site into a subdir (public/) or send "
                    "only that subdir on channel D"]
            signals.append(f"file:{cand}/index.html")
            return plan, node_eng
    return plan, node_eng


def workspace_roots(root, pkg):
    """Candidate package dirs for monorepos (best-effort globbing)."""
    pats = []
    ws_file = root / "pnpm-workspace.yaml"
    if ws_file.is_file():
        pats += re.findall(r"""-\s*["']?([^"'\n#]+)["']?""",
                           ws_file.read_text(encoding="utf-8",
                                             errors="replace"))
    if pkg and isinstance(pkg.get("workspaces"), list):
        pats += pkg["workspaces"]
    from glob import glob
    dirs = []
    for pat in pats:
        dirs += [Path(g) for g in glob(str(root / pat))
                 if Path(g).is_dir()]
    return dirs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("repo", help="github URL or local path")
    ap.add_argument("--branch")
    ap.add_argument("--workdir", default="/tmp/cfdeploys")
    ap.add_argument("--out")
    args = ap.parse_args()

    token = os.environ.get("GITHUB_TOKEN")
    if re.search(r"(^https?://|^git@|github\.com)", args.repo):
        root, branch = clone(args.repo, args.workdir, args.branch, token)
        owner, name = parse_repo(args.repo)
        source = args.repo
    else:
        root, branch = Path(args.repo).resolve(), (args.branch
                                                   or "main")
        owner, name = parse_repo(str(root))
        source = str(root)

    pkg = load_pkg(root)
    mono = bool((root / "pnpm-workspace.yaml").is_file()
                or (pkg and pkg.get("workspaces")))
    frag, node_eng = detect_one(root)
    signals = ([f"branch:{branch}", "detect:" + frag["type"]]
               + frag.pop("signals", []))

    plan = {
        "source": source,
        "owner": owner,
        "repo_name": name,
        "default_branch": branch,
        "local_path": str(root),
        "cf_project_name": sanitize_name(name),
        "compatibility_date": datetime.date.today().isoformat(),
        "node_engines": node_eng,
        "monorepo": mono,
    }
    plan.update(frag)
    plan["signals"] = signals + ([] if frag["type"] != "unknown" else
                                 ["no known framework markers found"])

    if mono or frag["type"] == "unknown":
        subs = []
        for d in workspace_roots(root, pkg) or []:
            rel = str(d.relative_to(root))
            sf, _ = detect_one(d, rel)
            if sf["type"] != "unknown":
                subs.append({"dir": rel, "type": sf["type"],
                             "channel": sf["channel"],
                             "build_command": sf["build_command"],
                             "output_dir": sf["output_dir"],
                             "signals": sf.pop("signals", [])})
        if subs:
            plan["monorepo_packages"] = subs
            if plan["type"] in ("unknown", "nodejs-no-framework"):
                plan["type"] = "monorepo"
                plan["channel"] = "ask-user"
                plan["preconditions"] = [
                    "pick one package (or ask user); set root_dir to its dir "
                    "(candidates: "
                    + ", ".join(s["dir"] for s in subs) + ")"]

    if plan["channel"] in ("pages-git", "direct-upload") and node_eng:
        m = re.search(r"(\d+)", node_eng)
        if m:
            plan["env_vars"]["NODE_VERSION"] = m.group(1)
    if plan["type"] not in ("hugo", "jekyll", "mkdocs") \
            and plan["install_command"] == "npm install" \
            and (root / "pnpm-lock.yaml").is_file():
        plan["install_command"] = "pnpm install --frozen-lockfile"
    elif (root / "yarn.lock").is_file():
        plan["install_command"] = "yarn install --frozen-lockfile"

    text = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
