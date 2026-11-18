#!/usr/bin/env bash
# Verify a deployed Cloudflare URL is live.
# usage: verify.sh <url> [expected_substring] [retries]
# Uses python3 (stdlib) so it works where curl is absent.
set -u
url="${1:?usage: verify.sh <url> [expected_substring] [retries]}"
expect="${2:-}"
retries="${3:-3}"

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT

for i in $(seq 1 "$retries"); do
  code=$(python3 - "$url" "$tmp" <<'PY'
import sys, urllib.request, urllib.error
url, out = sys.argv[1], sys.argv[2]
req = urllib.request.Request(url, headers={"User-Agent": "dsh-verify/1.0"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        data, status = r.read(), r.status
except urllib.error.HTTPError as e:
    data, status = e.read(), e.code
except Exception:
    print(0)
    sys.exit()
with open(out, "wb") as fh:
    fh.write(data)
print(status)
PY
)
  if [ "$code" = "200" ]; then
    title=$(python3 - "$tmp" <<'PY'
import re, sys
html = open(sys.argv[1], encoding="utf-8", errors="replace").read()
m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
if m:
    print(" ".join(m.group(1).split())[:120])
PY
)
    if [ -n "$expect" ] && ! grep -qi -- "$expect" "$tmp"; then
      echo "attempt $i: 200 but missing expected string: $expect"
    else
      echo "OK url=$url status=$code title=${title:-<none>}"
      exit 0
    fi
  else
    echo "attempt $i: status=${code:-0} (CDN propagation or config issue)"
  fi
  sleep $((i * 5))
done
echo "FAIL url=$url after $retries attempts"
exit 1
