#!/usr/bin/env bash
# Install the mitmproxy CA as a system cert on a rootable (google_apis) AVD,
# so HTTPS from unpinned apps is decryptable. Run after starting the AVD once.
set -e
CA="$HOME/.mitmproxy/mitmproxy-ca-cert.cer"
[ -f "$CA" ] || { echo "Run 'mitmdump' once to generate $CA, then re-run."; exit 1; }

adb root; adb wait-for-device
hashed="$(openssl x509 -inform PEM -subject_hash_old -in "$CA" | head -1)"
cp "$CA" "/tmp/${hashed}.0"

# classic /system path (older images)
if adb remount 2>/dev/null && adb push "/tmp/${hashed}.0" /system/etc/security/cacerts/ 2>/dev/null; then
  adb shell "chmod 644 /system/etc/security/cacerts/${hashed}.0"
  echo "Installed to /system/etc/security/cacerts/${hashed}.0"
else
  # Android 14 (API 34) APEX trust store — tmpfs overlay trick
  echo "Using APEX tmpfs overlay (Android 14)…"
  adb shell su 0 "mkdir -p /data/local/tmp/ca && cp /apex/com.android.conscrypt/cacerts/* /data/local/tmp/ca/ 2>/dev/null; \
    mount -t tmpfs tmpfs /apex/com.android.conscrypt/cacerts && \
    cp /data/local/tmp/ca/* /apex/com.android.conscrypt/cacerts/ 2>/dev/null; true"
  adb push "/tmp/${hashed}.0" /data/local/tmp/
  adb shell su 0 "cp /data/local/tmp/${hashed}.0 /apex/com.android.conscrypt/cacerts/ && chmod 644 /apex/com.android.conscrypt/cacerts/${hashed}.0"
  echo "Installed to APEX cacerts as ${hashed}.0 (valid until reboot)."
fi
echo "Done. If you used /system, run: adb reboot"
