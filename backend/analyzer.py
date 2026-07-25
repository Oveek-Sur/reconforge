"""AI-free static structure extraction from a decompiled APK.

Produces the "application structure" the user asked for even with no AI connected:
package/version, permissions, exported components, deep-link schemes/hosts,
hardcoded secrets (BuildConfig), endpoints/hosts, and RN/Hermes/Flutter detection.
"""
from __future__ import annotations
import re
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"

URL_RE = re.compile(rb"https?://[a-zA-Z0-9._\-]+(?:/[a-zA-Z0-9._\-/%?=&:@~+#{}]*)?")
API_PATH_RE = re.compile(rb"/(?:api|v[0-9]|graphql|oauth|rest|internal)/[a-zA-Z0-9_/{}.:\-]+")
SECRET_HINT = re.compile(
    r"(?i)(secret|token|api[_-]?key|passwd|password|auth[_-]?key|client[_-]?secret|private[_-]?key|dsn|access[_-]?key)"
)
# public-by-design keys we should NOT flag as sensitive (reduces false positives)
PUBLIC_KEY_HINT = re.compile(r"(?i)(client_id|site_key|app_id|application_id|public|recaptcha|turnstile|cloudflare)")


def inspect_apk(apk_path: str) -> dict:
    info = {
        "native_libs": [], "dex_count": 0, "is_react_native": False,
        "is_flutter": False, "rn_bundle": None, "assets": [],
    }
    libs = set()
    with zipfile.ZipFile(apk_path) as z:
        names = z.namelist()
    for n in names:
        if n.startswith("classes") and n.endswith(".dex"):
            info["dex_count"] += 1
        m = re.match(r"lib/[^/]+/(lib.+\.so)$", n)
        if m:
            libs.add(m.group(1))
        if n == "assets/index.android.bundle":
            info["rn_bundle"] = n
        if n.startswith("assets/") and n.count("/") == 1:
            info["assets"].append(n)
    info["native_libs"] = sorted(libs)
    info["is_react_native"] = bool(info["rn_bundle"]) or any(
        k in l for l in libs for k in ("libhermes", "libreactnative", "libjsc")
    )
    info["is_flutter"] = any("libflutter" in l for l in libs)
    return info


def _find_manifest(out_dir: str) -> Path | None:
    for c in (Path(out_dir) / "resources" / "AndroidManifest.xml", Path(out_dir) / "AndroidManifest.xml"):
        if c.exists():
            return c
    return None


def parse_manifest(out_dir: str) -> dict:
    res = {"package": None, "version": None, "permissions": [], "components": [], "deeplinks": []}
    mp = _find_manifest(out_dir)
    if not mp:
        return res
    try:
        root = ET.parse(mp).getroot()
    except Exception:
        return res
    res["package"] = root.get("package")
    res["version"] = root.get(ANDROID_NS + "versionName")
    for up in root.iter("uses-permission"):
        n = up.get(ANDROID_NS + "name")
        if n:
            res["permissions"].append(n)
    app = root.find("application")
    if app is None:
        return res
    for tag in ("activity", "activity-alias", "service", "receiver", "provider"):
        for el in app.iter(tag):
            name = el.get(ANDROID_NS + "name")
            exported = el.get(ANDROID_NS + "exported")
            has_filter = el.find("intent-filter") is not None
            if exported is None and has_filter:
                exported = "true(implied)"
            comp = {"type": tag, "name": name, "exported": exported, "schemes": []}
            for data in el.iter("data"):
                scheme = data.get(ANDROID_NS + "scheme")
                host = data.get(ANDROID_NS + "host")
                prefix = data.get(ANDROID_NS + "pathPrefix")
                if scheme:
                    entry = {"scheme": scheme, "host": host, "pathPrefix": prefix}
                    comp["schemes"].append(entry)
                    res["deeplinks"].append({"component": name, **entry})
            res["components"].append(comp)
    return res


def scan_buildconfig(out_dir: str, package: str | None) -> list[dict]:
    src = Path(out_dir) / "sources"
    candidates: list[Path] = []
    if package:
        p = src / package.replace(".", "/") / "BuildConfig.java"
        if p.exists():
            candidates.append(p)
    if not candidates:
        candidates = list(src.rglob("BuildConfig.java"))[:8]
    fields: list[dict] = []
    seen = set()
    for bc in candidates:
        try:
            text = bc.read_text("utf-8", "replace")
        except Exception:
            continue
        for m in re.finditer(r'String\s+(\w+)\s*=\s*"([^"]*)"', text):
            name, val = m.group(1), m.group(2)
            if not val or name in seen:
                continue
            seen.add(name)
            likely = bool(SECRET_HINT.search(name)) and not PUBLIC_KEY_HINT.search(name)
            fields.append({"name": name, "value": val, "likely_secret": likely, "file": str(bc)})
    return fields


def scan_endpoints(apk_path: str, rn_bundle: str | None, cap: int = 400) -> dict:
    hosts, paths = set(), set()
    blobs: list[bytes] = []
    try:
        with zipfile.ZipFile(apk_path) as z:
            if rn_bundle:
                blobs.append(z.read(rn_bundle))
    except Exception:
        pass
    for blob in blobs:
        for m in URL_RE.findall(blob):
            try:
                host = m.decode("utf-8", "replace").split("//", 1)[1].split("/", 1)[0]
                hosts.add(host)
            except Exception:
                pass
            if len(hosts) > cap:
                break
        for m in API_PATH_RE.findall(blob):
            paths.add(m.decode("utf-8", "replace"))
            if len(paths) > cap:
                break
    return {"hosts": sorted(hosts)[:cap], "api_paths": sorted(paths)[:cap]}


def analyze_apk(apk_path: str, out_dir: str) -> dict:
    apk = inspect_apk(apk_path)
    manifest = parse_manifest(out_dir)
    secrets = scan_buildconfig(out_dir, manifest.get("package"))
    endpoints = scan_endpoints(apk_path, apk.get("rn_bundle"))
    exported = [c for c in manifest["components"] if str(c.get("exported", "")).startswith("true")]
    notes = []
    if apk["is_react_native"]:
        notes.append("React Native + Hermes — decompile assets/index.android.bundle with hermes-dec for business logic.")
    if any(s["likely_secret"] for s in secrets):
        notes.append("Hardcoded secret-like values found in BuildConfig — verify each (many *_ID/site keys are public-by-design).")
    return {
        "package": manifest.get("package"),
        "version": manifest.get("version"),
        "apk": apk,
        "permissions": manifest["permissions"],
        "components_total": len(manifest["components"]),
        "exported_components": exported,
        "deeplinks": manifest["deeplinks"],
        "secrets": secrets,
        "endpoints": endpoints,
        "notes": notes,
    }
