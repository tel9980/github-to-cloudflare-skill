#!/usr/bin/env python3
"""Minimal Cloudflare API client (stdlib only).

Exists because channel A/B/C in this skill are documented as curl calls and
curl is not installed everywhere. Same endpoints, same JSON, no curl needed.
The token stays in the process (an env var read into a header), never in argv.

Env: CLOUDFLARE_API_TOKEN (required), CLOUDFLARE_ACCOUNT_ID (for {account}).

Usage:
  python3 cf.py --verify                     # token + account smoke test
  python3 cf.py GET  /accounts/{account}/pages/projects/<name>
  python3 cf.py POST /accounts/{account}/pages/projects --json '{"name":"x"}'
  python3 cf.py PATCH ... --json-file body.json
  python3 cf.py DELETE /accounts/{account}/pages/projects/<name>

Prints the HTTP status on stderr-ish prefix line, then the response body
(pretty-printed JSON when possible). Exit 0 for 2xx, 1 for other status,
2 for a missing token. The token value is redacted from every output line.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("method", nargs="?", help="GET|POST|PATCH|PUT|DELETE")
    ap.add_argument("path", nargs="?", help="API path, {account} is substituted")
    ap.add_argument("--json", dest="body")
    ap.add_argument("--json-file", dest="body_file")
    ap.add_argument("--verify", action="store_true", help="token+account check")
    a = ap.parse_args()

    token = os.environ.get("CLOUDFLARE_API_TOKEN", "").strip()
    account = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "").strip()
    if not token:
        print("CLOUDFLARE_API_TOKEN is not set", file=sys.stderr)
        return 2

    def redact(text):
        return text.replace(token, "***REDACTED***") if token else text

    def call(method, path, body=None):
        url = API + path.replace("{account}", account)
        data = None
        headers = {"Authorization": f"Bearer {token}",
                   "Content-Type": "application/json"}
        if body is not None:
            data = body.encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=headers,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode("utf-8", "replace")
        except Exception as e:  # network/DNS/TLS
            return 0, json.dumps({"error": redact(str(e))})

    if a.verify:
        s1, b1 = call("GET", "/user/tokens/verify")
        print(f"[token/verify] {s1}")
        print(redact(b1)[:400])
        s2, b2 = call("GET", "/accounts")
        print(f"[accounts] {s2}")
        try:
            ids = [x.get("id") for x in json.loads(b2).get("result", [])]
        except Exception:
            ids = []
        print("account ids:", ", ".join(i for i in ids if i) or "(none)")
        if account:
            print("CLOUDFLARE_ACCOUNT_ID match:", account in ids)
        ok = s1 == 200 and '"success":true' in b1.replace(" ", "")
        return 0 if ok else 1

    if not a.method or not a.path:
        ap.print_help()
        return 2

    body = a.body
    if a.body_file:
        body = open(a.body_file, encoding="utf-8").read()

    status, text = call(a.method.upper(), a.path, body)
    print(f"[{a.method.upper()} {a.path}] status={status}", file=sys.stderr)
    try:
        print(redact(json.dumps(json.loads(text), ensure_ascii=False,
                                indent=2)))
    except Exception:
        print(redact(text))
    return 0 if 200 <= status < 300 else 1


if __name__ == "__main__":
    sys.exit(main())
