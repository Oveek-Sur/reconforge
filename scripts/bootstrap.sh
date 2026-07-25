#!/usr/bin/env bash
# ReconForge self-setup — installs Android SDK + emulator + system image + tools
# on Kali/Debian. Idempotent, safe to re-run, streams progress, ends with a SUMMARY.
# Needs passwordless sudo for the apt steps (see note at end if it stalls).
set -uo pipefail
say(){ echo "[setup] $*"; }
ok(){ echo "[ok]   $*"; }
warn(){ echo "[warn] $*"; }

API=34
IMG="system-images;android-${API};google_apis;x86_64"   # google_apis = rootable (needed for mitmproxy CA)
AVD="rf${API}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
CT="$ANDROID_HOME/cmdline-tools/latest"
export PATH="$CT/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
SUDO="sudo -n"

# 1) apt dependencies
say "installing apt packages (jdk, adb, mitmproxy, qemu-kvm, unzip, ripgrep)…"
$SUDO apt-get update -y 2>&1 | tail -1 || warn "apt update failed (need passwordless sudo?)"
$SUDO apt-get install -y openjdk-17-jdk-headless unzip curl ripgrep mitmproxy \
      qemu-kvm libvirt-daemon-system android-tools-adb 2>&1 | tail -2 || warn "some apt packages failed"
ok "apt step done"

# 2) Android command-line tools
if [ ! -x "$CT/bin/sdkmanager" ]; then
  say "installing Android cmdline-tools…"
  mkdir -p "$ANDROID_HOME/cmdline-tools"
  LOCAL="$(ls "$HOME"/Downloads/commandlinetools-linux-*_latest.zip 2>/dev/null | head -1)"
  TMP=/tmp/rf-cmdtools.zip
  if [ -n "$LOCAL" ]; then say "using local $LOCAL"; cp "$LOCAL" "$TMP";
  else say "downloading cmdline-tools…"; curl -fsSL -o "$TMP" \
       "https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip" || warn "download failed"; fi
  ( cd "$ANDROID_HOME/cmdline-tools" && rm -rf latest _tmp && unzip -q "$TMP" -d _tmp && mv _tmp/cmdline-tools latest && rm -rf _tmp )
fi
[ -x "$CT/bin/sdkmanager" ] && ok "cmdline-tools ready" || warn "cmdline-tools missing"

# 3) SDK packages via sdkmanager (fetches correct Linux/x86_64 builds)
if [ -x "$CT/bin/sdkmanager" ]; then
  say "accepting SDK licenses…"; yes | "$CT/bin/sdkmanager" --licenses >/dev/null 2>&1 || true
  say "installing platform-tools + emulator + system image (may take several minutes)…"
  "$CT/bin/sdkmanager" "platform-tools" "emulator" "platforms;android-${API}" "$IMG" 2>&1 | tail -3 || warn "sdkmanager failed"
  ok "sdk packages step done"
fi

# 4) AVD
if "$ANDROID_HOME/emulator/emulator" -list-avds 2>/dev/null | grep -qx "$AVD"; then
  ok "AVD '$AVD' already exists"
else
  say "creating AVD '$AVD'…"
  echo no | "$CT/bin/avdmanager" create avd -n "$AVD" -k "$IMG" --device pixel_6 2>&1 | tail -2 && ok "AVD created" || warn "AVD create failed"
fi

# 5) KVM acceleration
if [ -e /dev/kvm ]; then
  $SUDO adduser "$USER" kvm >/dev/null 2>&1 || true
  ok "/dev/kvm present (re-login or 'newgrp kvm' to apply group)"
else
  warn "/dev/kvm MISSING — enable NESTED VIRTUALIZATION on the VM host, else the emulator is unusably slow"
fi

# 6) persist env for ReconForge
if ! grep -q 'ANDROID_HOME' "$HOME/.bashrc" 2>/dev/null; then
  { echo "export ANDROID_HOME=$ANDROID_HOME";
    echo 'export PATH=$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH';
  } >> "$HOME/.bashrc"
  ok "added ANDROID_HOME + PATH to ~/.bashrc"
fi

# 7) summary
echo "──────────────── SUMMARY ────────────────"
command -v adb >/dev/null 2>&1 && echo "adb        : $(adb --version 2>/dev/null | head -1)" || echo "adb        : MISSING"
[ -x "$ANDROID_HOME/emulator/emulator" ] && echo "emulator   : installed" || echo "emulator   : MISSING"
avds="$("$ANDROID_HOME/emulator/emulator" -list-avds 2>/dev/null | tr '\n' ' ')"; echo "avds       : ${avds:-none}"
command -v mitmdump >/dev/null 2>&1 && echo "mitmproxy  : $(mitmdump --version 2>/dev/null | head -1)" || echo "mitmproxy  : MISSING"
[ -e /dev/kvm ] && echo "kvm        : yes" || echo "kvm        : NO (enable nested virt)"
echo "──────────────────────────────────────────"
echo "If apt stalled: enable passwordless sudo once →"
echo "  echo \"\$USER ALL=(ALL) NOPASSWD:ALL\" | sudo tee /etc/sudoers.d/reconforge"
