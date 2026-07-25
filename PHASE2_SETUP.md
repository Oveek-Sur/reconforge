# ReconForge — Phase 2 setup (emulator + mitmproxy) on Kali

## What to collect / install
```bash
# ── base tools ────────────────────────────────────────────────
sudo apt update
sudo apt install -y default-jdk android-tools-adb ripgrep openssl mitmproxy
# optional smoother native mirror:
sudo apt install -y scrcpy

# ── KVM acceleration (REQUIRED for a usable x86_64 emulator) ───
sudo apt install -y qemu-kvm libvirt-daemon-system
sudo adduser "$USER" kvm
ls -l /dev/kvm        # must exist & be group-accessible
#  ⚠️ If Kali runs inside a VM, enable NESTED VIRTUALIZATION on the host
#     (VMware: "Virtualize Intel VT-x/EPT"; VirtualBox: VBoxManage modifyvm <vm> --nested-hw-virt on)

# ── Android SDK: cmdline-tools + emulator + a ROOTABLE image ───
export ANDROID_HOME="$HOME/Android/Sdk"
mkdir -p "$ANDROID_HOME/cmdline-tools"
# download commandlinetools-linux-*.zip from https://developer.android.com/studio#command-tools
#   unzip so that: $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager exists
cd "$ANDROID_HOME/cmdline-tools" && unzip ~/Downloads/commandlinetools-linux-*.zip && mv cmdline-tools latest
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"

yes | sdkmanager --licenses
sdkmanager "platform-tools" "emulator" "platforms;android-34" \
           "system-images;android-34;google_apis;x86_64"   # google_apis = ROOTABLE (needed for CA)

# ── create an AVD ─────────────────────────────────────────────
echo no | avdmanager create avd -n rf34 \
     -k "system-images;android-34;google_apis;x86_64" --device pixel_6
```
Add the exports to `~/.bashrc` so ReconForge finds `emulator`/`adb`.

> **Why google_apis (not google_play):** only a rootable image lets `adb root` +
> `-writable-system` remount `/system`, which is required to install the mitmproxy
> CA as a **system** certificate so HTTPS from apps (with no pinning, like Syfe) is
> decryptable. google_play images are locked.

## Install the mitmproxy CA on the emulator (one time)
Start the AVD once (ReconForge ▶ Start, "writable-system" on), then:
```bash
mitmdump &                # generates ~/.mitmproxy/mitmproxy-ca-cert.cer, then Ctrl-C
bash reconforge/scripts/setup_mitm_ca.sh   # pushes CA to /system, reboots
```
On Android 14 (API 34) the trust store lives in an APEX; if the push is rejected,
either launch with `-writable-system` (the setup script uses the tmpfs remount
fallback) or use an API-33 image.

## Use it in ReconForge
1. `bash run.sh` → open the UI.
2. Right pane → **Screen**: pick your AVD → ▶ Start → wait for boot → the mirror appears
   (tap/swipe/keys work). **Install APK** and **Launch** buttons drive the target app.
3. Right pane → **Network**: click **Start intercept** (spawns `mitmdump` on :8080 and
   sets the device proxy). Every API call appears live; click one to inspect, or
   "Send to agent" to have the assistant analyze it.
```
