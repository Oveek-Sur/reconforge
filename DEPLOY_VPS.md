# ReconForge — Google VPS-এ চালানো (PC-র উপর চাপ না ফেলে)

লক্ষ্য: ভারী কাজ (jadx decompile, AI, analysis) GCP VPS-এ চলবে, তোমার PC ফ্রি থাকবে। আমি এখান থেকেই (তোমার PC → tunnel → VPS) কমান্ড দিয়ে সব চালাতে পারব — ঠিক Kali VM-এর মতোই।

## 🧠 আগে বোঝো: কোনটা memory খায়
| কাজ | RAM | GCP-তে |
|-----|-----|--------|
| **Android emulator** | 2–4 GB | **nested-virt দরকার** (কঠিন, নিচে) |
| **jadx decompile** | 2–6 GB (heap) | সহজে চলে; heap এখন **configurable** |
| ReconForge + AI + mitmproxy | <500 MB | সহজ |

তোমার PC-র চাপের মূল কারণ = **VMware Kali VM + emulator একসাথে**। তাই সবচেয়ে কার্যকর: **static ভারী কাজ (jadx) VPS-এ সরাও**; emulator লাগবে শুধু dynamic-এর সময় (আর UAT backend তো এখন down, তাই dynamic এখন জরুরি নয়)।

## ✅ সুপারিশকৃত architecture (নিরাপদ + সহজ)
```
তোমার PC  ──SSH tunnel (8777)──►  GCP VPS: ReconForge (127.0.0.1 bind) + jadx
   │
   └── আমি (Claude) PC থেকে http://127.0.0.1:8777 হিট করি → tunnel দিয়ে VPS-এ যায়
```
- ReconForge VPS-এ **localhost-এ bind** → পাবলিক IP-তে কিছুই খোলা নয় → **RCE ঝুঁকি শূন্য**।
- tunnel: `gcloud compute ssh <vm> --zone <zone> -- -N -L 8777:localhost:8777`
- এরপর আমি আগের মতোই `http://127.0.0.1:8777/api/exec` (strong token) দিয়ে VPS চালাই।

## 🚀 ধাপ (একবার)
1. **VM বানাও** (static-only, emulator ছাড়া — এখনকার জন্য যথেষ্ট):
   ```bash
   gcloud compute instances create reconforge \
     --machine-type=e2-standard-4 --boot-disk-size=40GB \
     --image-family=debian-12 --image-project=debian-cloud --zone=asia-south1-a
   ```
   `e2-standard-4` = 4 vCPU / 16 GB (jadx-এর জন্য আরামদায়ক)। ছোট বাজেটে `e2-standard-2` (2 vCPU/8 GB) + `RECONFORGE_JADX_XMX=4g`।
2. **Deploy:**
   ```bash
   gcloud compute ssh reconforge --zone asia-south1-a
   git clone https://github.com/Oveek-Sur/reconforge && cd reconforge
   bash scripts/deploy_vps.sh          # jadx+deps বসাবে, STRONG token ছাপাবে, চালু করবে
   ```
   → স্ক্রিপ্ট **remote token** ছাপবে — সেটা আমাকে দিও (config.json-এও লেখা থাকবে)।
3. **Tunnel খোলো (তোমার PC থেকে):**
   ```bash
   gcloud compute ssh reconforge --zone asia-south1-a -- -N -L 8777:localhost:8777
   ```
4. আমাকে দাও: **token** (আর নিশ্চিত করো tunnel চালু) → আমি `127.0.0.1:8777` দিয়ে APK আপলোড/decompile/analyze চালাই।

## 💾 Memory কমানোর knob (এখন যুক্ত করলাম)
`deploy_vps.sh`/environment-এ সেট করো:
- `RECONFORGE_JADX_XMX=2g` — jadx heap (ছোট VM-এ; বড় box-এ 8g)
- `RECONFORGE_JADX_THREADS=2` — কম thread = কম peak RAM (একটু ধীর)
- `RECONFORGE_JADX_LEAN=1` — debug-info বাদ = কম RAM/সময়
- **jadx আর emulator একসাথে চালিও না** (peak RAM যোগ হয়)।
- খরচ বাঁচাতে: কাজ শেষে `gcloud compute instances stop reconforge` (per-use billing)।

## 📱 Emulator VPS-এ চাই? (nested virtualization)
GCP-তে emulator-কে KVM লাগে → **nested-virt VM** বানাতে হয় (সব machine-type-এ নেই, একটু ধীর):
```bash
gcloud compute instances create reconforge-emu \
  --machine-type=n2-standard-4 --zone=asia-south1-a \
  --enable-nested-virtualization \
  --min-cpu-platform="Intel Haswell" \
  --image-family=debian-12 --image-project=debian-cloud --boot-disk-size=60GB
```
তারপর VM-এ `bash scripts/bootstrap.sh` (SDK+emulator+image নামায়)। **সৎ কথা:** GCP nested-virt emulator তোমার local KVM-এর চেয়ে ধীর; UAT backend down থাকায় **এখন এর দরকার নেই** — static কাজ VPS-এ, emulator লাগলে তখন local Kali-তে বা এই nested VM-এ।

## 🔐 নিরাপত্তা (গুরুত্বপূর্ণ)
- `/api/exec` = **remote root RCE** (token-gated)। **পাবলিক IP-তে কখনো খুলো না** (0.0.0.0 + দুর্বল token = যে কেউ দখল নেবে)। tunnel + localhost-bind = নিরাপদ, তাই ওটাই default রাখলাম।
- যদি একান্তই পাবলিক লাগে: GCP firewall দিয়ে শুধু তোমার IP allow করো + `secrets.token_urlsafe` token।
- এই config.json (আসল key/token) কখনো git-এ push করো না (gitignored)।
