#!/usr/bin/env python3
"""
ReconForge — spawn an app under Frida with an instrumentation script and keep
the session alive (for background use while a proxy captures traffic).

Usage: python3 frida_spawn.py <package> <script.js> [keepalive_seconds]
"""
import sys
import time
import frida

pkg = sys.argv[1] if len(sys.argv) > 1 else "com.syfe"
script_path = sys.argv[2] if len(sys.argv) > 2 else "/tmp/unpin.js"
keepalive = int(sys.argv[3]) if len(sys.argv) > 3 else 1800


def on_message(message, data):
    if message.get("type") == "send":
        print("[frida] " + str(message.get("payload")), flush=True)
    elif message.get("type") == "error":
        print("[frida-error] " + str(message.get("description")), flush=True)


def main():
    device = frida.get_usb_device(timeout=10)
    print(f"[*] Device: {device}", flush=True)
    pid = device.spawn([pkg])
    print(f"[*] Spawned {pkg} pid={pid}", flush=True)
    session = device.attach(pid)
    with open(script_path) as f:
        src = f.read()
    script = session.create_script(src)
    script.on("message", on_message)
    script.load()
    device.resume(pid)
    print(f"[*] Resumed {pkg}; hooks active; keepalive={keepalive}s", flush=True)
    try:
        time.sleep(keepalive)
    except KeyboardInterrupt:
        pass
    print("[*] Keepalive elapsed; detaching", flush=True)


if __name__ == "__main__":
    main()
