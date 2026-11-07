#!/bin/bash
# Join the frame to Wi-Fi. Prompts for the password with echo off, hashes it here with
# wpa_passphrase (the frame only ever gets the derived PSK, never the plaintext), pushes
# /etc/wpa_supplicant/wpa_supplicant.conf over the USB serial shell, then connects and runs DHCP.
# Nothing is written on this machine.
set -euo pipefail
cd "$(dirname "$0")"

COUNTRY=${COUNTRY:-US}   # regulatory domain (ISO 3166 alpha-2)
[[ $COUNTRY =~ ^[A-Z]{2}$ ]] || { echo "COUNTRY must be two capital letters, e.g. US, DE" >&2; exit 1; }
read -rp "SSID: " ssid
[ -n "$ssid" ] || { echo "no SSID given" >&2; exit 1; }
read -rsp "Password for \"$ssid\" (hidden): " pass
echo
[ ${#pass} -ge 8 ] || { echo "WPA passwords are at least 8 characters" >&2; exit 1; }

# wpa_passphrase writes the plaintext as a #psk= comment; drop that line.
conf=$(wpa_passphrase "$ssid" "$pass" | grep -v '^\s*#psk=')
unset pass
conf=$(printf 'ctrl_interface=/var/run/wpa_supplicant\ncountry=%s\n\n%s\n' "$COUNTRY" "$conf")
b64=$(printf '%s\n' "$conf" | base64 -w0)

sudo ./frame-sh "mkdir -p /etc/wpa_supplicant && echo $b64 | base64 -d > /etc/wpa_supplicant/wpa_supplicant.conf && chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf && echo config written" 20
sudo ./frame-sh "iw reg set $COUNTRY; "'killall wpa_supplicant 2>/dev/null; wpa_supplicant -B -i wlan0 -c /etc/wpa_supplicant/wpa_supplicant.conf >/dev/null && sleep 6 && iw dev wlan0 link | grep -E "Connected|SSID|signal|tx bitrate"' 30
sudo ./frame-sh 'udhcpc -i wlan0 -q -n -t 10 2>&1 | tail -2; ip addr show wlan0 | grep "inet "; ip route | grep default' 60
