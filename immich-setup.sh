#!/bin/bash
# Give the frame its Immich API key. Prompts with echo off and sends the key straight to the
# frame over SSH (/etc/aeezo-frame/immich.key, mode 600); nothing is stored on this machine.
# Then asks Immich, from the frame, for one random photo and its preview to prove the key works.
set -euo pipefail
#   FRAME=root@<frame-ip> IMMICH_URL=http://<server-ip>:2283 ./immich-setup.sh
# IMMICH_URL must be reachable FROM THE FRAME (it is tested from there). Put the same URL in
# /etc/aeezo-frame/frame.conf as IMMICH_URL=.
: "${FRAME:?set FRAME=root@<frame-ip>}"
: "${IMMICH_URL:?set IMMICH_URL=http://<server-ip>:2283}"
# it travels through the remote shell, so allow only plain URL characters
[[ $IMMICH_URL =~ ^https?://[A-Za-z0-9._:/-]+$ ]] || { echo "IMMICH_URL looks odd: $IMMICH_URL" >&2; exit 1; }

read -rsp "Immich API key (hidden): " key
echo
key=$(printf '%s' "$key" | tr -d '\r\n')
if ! [[ $key =~ ^[A-Za-z0-9_-]{20,128}$ ]]; then
	echo "That isn't an Immich API key (${#key} chars; a key is one unbroken string of letters," >&2
	echo "digits, - and _). Nothing was sent. Copy the key again and re-run." >&2
	exit 1
fi

printf '%s\n' "$key" | ssh -o BatchMode=yes "$FRAME" \
	'umask 077; mkdir -p /etc/aeezo-frame && cat > /etc/aeezo-frame/immich.key'
unset key

ssh -o BatchMode=yes "$FRAME" python3 - "$IMMICH_URL" <<'EOF'
import json, sys, urllib.request
key = open("/etc/aeezo-frame/immich.key").read().strip()
url = sys.argv[1].rstrip("/")
def req(method, path, body=None):
    r = urllib.request.Request(url + path, method=method, data=json.dumps(body).encode() if body else None,
                               headers={"x-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return resp.read()
try:
    a = json.loads(req("POST", "/api/search/random", {"size": 1, "type": "IMAGE"}))
    print("random search: OK" if a else "random search: OK but returned no images")
    if a:
        n = len(req("GET", f"/api/assets/{a[0]['id']}/thumbnail?size=preview"))
        print(f"preview download: OK ({n // 1024} KiB)")
except urllib.error.HTTPError as e:
    print(f"FAILED: Immich said {e.code}: {e.read()[:200].decode(errors='replace')}")
    if e.code == 401:
        print("401 = Immich doesn't recognise this key (mistyped, revoked, or a different server).")
    elif e.code == 403:
        print("403 = valid key, missing permission: it needs asset.read and asset.view (album.read for albums).")
    raise SystemExit(1)
EOF
echo "Key works. Restarting the slideshow."
ssh -o BatchMode=yes "$FRAME" rc-service aeezo-frame restart
