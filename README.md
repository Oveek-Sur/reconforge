# ReconForge — Agentic APK Pentest Workbench

An APK reverse-engineering + bug-hunting workbench for Kali Linux. Drop an APK →
it decompiles with jadx (live progress) → gives you a 3-pane IDE: **folders (left) |
AI chat (center) | Android emulator (right)** — with an autonomous agent that can drive
your Kali tools, terminal, `adb`, and the network to hunt bugs like a pentester.

> Authorized security testing only. ReconForge executes what *you* direct on *your*
> machine and authorized targets. You are responsible for scope & rules of engagement.

## Design goals
- **Runs on Kali with just Python** (zero front-end build; FastAPI serves a self-contained UI).
- **Works offline too:** decompile + full static structure (manifest, components, deep-links,
  endpoints, secrets, RN/Hermes) needs no AI. The AI is an accelerator, not a dependency.
- **Pluggable LLM providers:** Azure-OpenAI (GPT), Anthropic, OpenRouter, Google Vertex/Gemini —
  switch in settings; a "Test agentic" check validates tool-calling before you save.
- **Agentic:** the assistant has tools — shell (opt. sudo), read/list/grep files, HTTP probe,
  `adb`, jadx, and a static-analyzer — and loops autonomously toward a goal.

## Architecture
```
reconforge/
├── backend/                 # Python brain (FastAPI + WebSocket)
│   ├── main.py              # routes, serves UI, WS progress + chat
│   ├── decompiler.py        # jadx runner, streams progress %
│   ├── analyzer.py          # AI-free static structure extraction
│   ├── agent.py             # tool-calling agent loop
│   ├── tools.py             # shell/read/grep/http/adb/jadx tools + schemas
│   ├── config.py            # providers, API keys, settings (JSON)
│   ├── emulator.py          # AVD / headless / scrcpy / screenshot (phase 2)
│   └── providers/           # anthropic, openai(azure/openrouter), gemini/vertex
├── frontend/index.html      # zero-build 3-pane SPA (served by FastAPI)
├── data/                    # per-APK workspaces (decompiled output, reports)
└── run.sh                   # one-command launch on Kali
```

## Data flow
1. **Analyze:** `POST /api/analyze {apk}` → `decompiler.run_jadx` streams `progress %`
   over `WS /ws/progress` → on finish, `analyzer.analyze_apk` builds the static structure.
2. **Explore:** `GET /api/tree`, `GET /api/file` feed the left file tree.
3. **Hunt:** `WS /ws/chat` → `agent.Agent` loops: LLM ↔ tools (Kali) until done, streaming
   tokens + tool calls + results to the UI.
4. **Run/Intercept (phase 2):** `emulator.py` launches an AVD (or headless) and mirrors it
   on the right; a mitmproxy sidecar streams intercepted API calls.

## Quick start (Kali)
```bash
cd reconforge
python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
sudo apt-get install -y jadx android-tools-adb        # + optional: aapt, mitmproxy, scrcpy
python backend/main.py                                # open http://127.0.0.1:8777
```
Set your model provider + API key in the ⚙️ settings panel, hit **Test agentic**, then
drop an APK.

## Roadmap
- [x] jadx decompile with live progress
- [x] AI-free static structure (manifest, components, deep-links, endpoints, RN/Hermes)
- [x] Agentic chat with Kali tool-calling (shell/read/grep/http/adb)
- [x] Pluggable providers (Azure-OpenAI, Anthropic, OpenRouter, Gemini)
- [ ] Embedded emulator (scrcpy mirror + headless screenshot stream)
- [ ] Live mitmproxy API-intercept panel
- [ ] Hermes/RN bundle auto-decompile (hermes-dec) integration
- [ ] Saved "playbooks" (recon → verify → report)
```
