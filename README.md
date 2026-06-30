# Doubleword × opencode (ocx registry)

One-step setup for using [Doubleword](https://doubleword.ai) in [opencode](https://opencode.ai)
via [ocx](https://github.com/kdcokenny/ocx). Installs:

- **`doubleword`** — realtime provider (`/v1/chat/completions`, OpenAI-compatible).
- **`doubleword-flex`** — the same models on the **flex (async) tier** (`service_tier: flex`):
  slower, cheaper. Works as a normal model because flex now streams SSE.
- **`small_model`** pinned to realtime, so title/summary stays fast and only your answers pay
  flex latency.
- **`doubleword_async`** — an MCP tool that runs a prompt on the flex tier and returns the result
  (fire-and-forget async from any model/agent).
- **`dw-flex`** — a background subagent pinned to the flex tier for non-urgent work.

No API key is stored in this repo. Each user supplies their own via `DOUBLEWORD_API_KEY`
(resolved at runtime with opencode's `{env:...}` substitution).

## Prerequisites
- [opencode](https://opencode.ai) installed
- [ocx](https://github.com/kdcokenny/ocx): `npm i -g ocx`
- `python3` (the MCP tool is stdlib-only — no pip installs)
- A Doubleword API key: `export DOUBLEWORD_API_KEY=sk-...`

## Quick start (local, with Docker)
Run the registry as a container, install it into opencode, done. The container is only needed
during install — the components get copied into your config.

```bash
git clone <this-repo> && cd doubleword-opencode-ocx
export DOUBLEWORD_API_KEY=sk-...

# 1. serve the registry locally
docker compose up -d --build

# 2. install into opencode
ocx init --global                                  # first time only
ocx registry add http://localhost:8077 --name dw --global
ocx add dw/doubleword --global                     # providers + flex + MCP tool + agent

# 3. stop the container — files are now in ~/.config/opencode
docker compose down

# 4. use it
opencode --model doubleword/moonshotai/Kimi-K2.6        # realtime (fast)
opencode --model doubleword-flex/moonshotai/Kimi-K2.6   # flex (async, cheaper)
```
In chat you can also fire an async job from any model:
> Use the doubleword_async tool to summarise these notes: ...

That's the whole setup — afterwards it's just `opencode`. Models included:
`moonshotai/Kimi-K2.6`, `zai-org/GLM-5.2-FP8` (add more in `registry.jsonc`); use only models
deployed on your Doubleword account. Other install methods (no Docker, hosted registry, sandbox)
are below.

## What to expect
- **Realtime**: instant streaming, as usual.
- **Flex**: a pause (≈seconds when the queue is empty, up to ~60s when busy), then the whole
  answer at once — it's SSE-framed but buffered, not token-by-token. Best for non-urgent work.

## Background: why a local server
ocx installs from an **http/https** URL only (it rejects local paths and `file://`), so the
registry must be served over HTTP — but only for the moment of install. The components are copied
into your opencode config, so you stop the server right after (as in Quick start). The Quick start
uses Docker Compose; the alternatives below do the same thing differently.

### Without Docker (plain server)
```bash
ocx build . --out dist                          # if dist/ isn't already built
( cd dist && python3 -m http.server 8077 ) &    # or: go run .   (serves dist/ on :8077)

export DOUBLEWORD_API_KEY=sk-...
ocx init --global
ocx registry add http://127.0.0.1:8077 --name dw --global
ocx add dw/doubleword --global
pkill -f "http.server 8077"                     # stop the server
opencode --model doubleword-flex/moonshotai/Kimi-K2.6
```

### Docker without compose / extras
```bash
docker build -t doubleword-ocx .
docker run -d -p 8077:8077 --name doubleword-ocx doubleword-ocx   # then ocx registry add ... as above
docker rm -f doubleword-ocx                                        # stop when done
```
- Change the port: `PORT=9000 docker compose up -d` (or `-e PORT=9000 -p 9000:9000` on plain docker).
- `ocx update`/`ocx verify` re-contact the registry URL, so restart the server for those.
- First `docker build` can hit a transient `DeadlineExceeded` pulling `golang:1.23-alpine` from
  Docker Hub — run `docker pull golang:1.23-alpine` once, then rebuild.

### Try it in a sandbox first (don't touch your real config)
Prefix the `ocx` + `opencode` commands with `HOME=/tmp/dw-try` so everything installs into a
throwaway `/tmp/dw-try/.config/opencode` instead of your real one:
```bash
( cd dist && python3 -m http.server 8077 ) &
export DOUBLEWORD_API_KEY=sk-...
HOME=/tmp/dw-try ocx init --global
HOME=/tmp/dw-try ocx registry add http://127.0.0.1:8077 --name dw --global
HOME=/tmp/dw-try ocx add dw/doubleword --global
HOME=/tmp/dw-try opencode --model doubleword-flex/moonshotai/Kimi-K2.6
```

## Publishing (to share with anyone)
ocx installs from a static URL where `index.json` is reachable. To make this registry installable
by your team:
1. Push this repo to a **public** GitHub repo (the registry must be reachable by `ocx`).
2. `ocx build . --out dist`.
3. Host `dist/` as static files — pick one:
   - **GitHub Pages**: enable Pages for the repo, serving `dist/` (or commit `dist/` to a `gh-pages`
     branch). URL becomes `https://<user>.github.io/<repo>`.
   - **Raw URL**: commit `dist/` and use `https://raw.githubusercontent.com/<user>/<repo>/main/dist`.
   - Or any host (Cloudflare Workers / Vercel / Netlify) serving `dist/`.
4. Share: `ocx registry add <that-url> --name dw --global` then `ocx add dw/doubleword --global`.

## Notes & caveats
- **MCP tool path**: the `doubleword_async` MCP server is launched from
  `{env:HOME}/.config/opencode/tools/doubleword-async/dw_async_mcp.py`. This assumes a **global**
  install at the default config location (`~/.config/opencode`). If you use a custom
  `XDG_CONFIG_HOME` or a project-scoped install, edit the `mcp.doubleword-async.command` path in
  your `opencode.json` to point at the installed script.
- Config-only **flex is the primary path**; the MCP tool is complementary (use it to fire a
  discrete async job from a realtime chat, rather than switching the whole turn to flex).
- Once Doubleword is an official [models.dev](https://models.dev) provider, the realtime provider
  block becomes unnecessary (just a key) — the flex provider + MCP tool remain useful.

## Repo layout
```
registry.jsonc                       # registry manifest (3 components)
files/mcp/dw_async_mcp.py            # async MCP tool (stdlib only)
files/agent/dw-flex.md               # flex background subagent
dist/                                # built output (generated by `ocx build`)
main.go                              # static server that embeds + serves dist/
go.mod                               # (no dependencies — stdlib only)
Dockerfile                           # self-contained image: docker run -p 8077:8077
docker-compose.yml                   # docker compose up -d --build
```
