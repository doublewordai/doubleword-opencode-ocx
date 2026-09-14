# Doubleword × opencode (ocx registry)

One-step setup for using [Doubleword](https://doubleword.ai) in [opencode](https://opencode.ai)
via [ocx](https://github.com/kdcokenny/ocx). Installs:

- **`doubleword`**: realtime provider on Doubleword's Anthropic-compatible Messages endpoint
  (`/v1/messages`, wired with `@ai-sdk/anthropic`). This wiring is what turns **prompt caching**
  on; see [Prompt caching](#prompt-caching) for why the OpenAI-compatible wiring does not cache.
- **`doubleword-flex`**: the same models on the **flex (async) tier** (`service_tier: flex`,
  `/v1/chat/completions`, OpenAI-compatible): slower, cheaper. Works as a normal model because
  flex now streams SSE. No prompt caching on this tier (see below).
- **`small_model`** pinned to realtime, so title/summary stays fast and only your answers pay
  flex latency.
- **`doubleword_async`** — an MCP tool that runs a prompt on the flex tier and returns the result
  (fire-and-forget async from any model/agent).
- **`dw-flex`** — a background subagent pinned to the flex tier for non-urgent work.

No API key is stored in this repo. Each user supplies their own via `DOUBLEWORD_API_KEY`
(resolved at runtime with opencode's `{env:...}` substitution).

## Prerequisites
- [opencode](https://opencode.ai) installed
  ```bash
  curl -fsSL https://opencode.ai/install | bash
  ```
- [ocx](https://github.com/kdcokenny/ocx): `npm i -g ocx` or `bun i -g ocx`
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
ocx init --global                                  # This is only necessary for the first time
ocx registry add http://localhost:8077 --name dw --global
ocx add dw/doubleword --global                     # providers + flex + MCP tool + agent

# 3. stop the container — files are now in ~/.config/opencode
docker compose down

# 4. use it
# Either you can just run opencode and navigate the menus to choose a model (select /models to see options)
opencode
# or you can initialise it with a model when you start it, like this example:
opencode --model doubleword/moonshotai/Kimi-K2.6        # realtime (fast)
opencode --model doubleword-flex/moonshotai/Kimi-K2.6   # flex (async, cheaper)
```

## Updating after changes to the registry
You installed with `--global`, so **every `ocx` command below needs `-g`/`--global`** — its
lockfile lives in `~/.config/opencode`, not in this repo. (Without it you get
`No ocx.jsonc found in .opencode/ or project root`.)

```bash
# 1. rebuild the static registry from your edited files/ + registry.jsonc
ocx build . --out dist

# 2. rebuild + restart the container so it serves the new dist
docker compose up -d --build

# 3. update the installed FILE-backed components (the MCP tool .py + the agent .md).
#    --all reconciles every changed component without you needing to paste hashes.
ocx update --all --global

# 4. re-apply the bundle's config (provider / models / small_model).
#    The `doubleword` bundle has no files, so step 3 never touches it — only `add`
#    rewrites those blocks in opencode.jsonc. Run this whenever you change a provider,
#    add/remove a model, or change small_model.
ocx add dw/doubleword --global

# 5. stop the registry again
docker compose down

# 6. refresh opencode's model cache if you added/changed models
opencode --refresh
```

### Why each command, and the gotcha you'll hit
- **`ocx update` vs `ocx add`.** `update` re-copies changed *files* (the `doubleword-async-tool`
  `.py` and `doubleword-flex-agent` `.md`). `add` re-writes the *config blocks* in
  `opencode.jsonc` (provider, models, `small_model`, MCP server entry). File changes → `update`;
  config changes → `add`. When in doubt, run both (update first, then add).
- **The `No ocx.jsonc found` error.** You ran an `ocx update`/`ocx add` without `--global`. ocx
  then looks for a *project-local* lockfile in the current directory and fails. Add `-g`.
- **The hash command ocx prints.** When a file component changed, `ocx add` refuses it and prints
  `Use 'ocx update http://localhost:8077::dw/...@sha256:<old-hash>'`. That suggestion **omits
  `--global`** — running it verbatim is exactly what triggers the error above. Either append
  `--global` to it, or just skip it and run `ocx update --all --global`.
- **`timeout` in the MCP block is dropped.** opencode's MCP schema has no `timeout` field, so
  `ocx build` strips it — it never reaches `opencode.jsonc`. Don't rely on it.
- **Sanity check** that an update landed (installed copy should match what the container serves):
  ```bash
  shasum -a 256 ~/.config/opencode/tools/doubleword-async/dw_async_mcp.py
  curl -s http://localhost:8077/components/doubleword-async-tool/mcp/dw_async_mcp.py | shasum -a 256
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
- **Prompt caching**: on for the realtime provider, off for flex. Details below.

## Prompt caching
The realtime `doubleword` provider is wired with `@ai-sdk/anthropic` against
`https://api.doubleword.ai/v1` (so `/v1/messages`) specifically to get prompt caching. It is not
a cosmetic choice, and swapping it back to `@ai-sdk/openai-compatible` silently disables caching.

**Why.** opencode only injects `cache_control` breakpoints inside `applyCaching()`, and that
function is called behind an Anthropic-shaped gate
(`packages/opencode/src/provider/transform.ts`):

```js
providerID === "anthropic" || providerID === "google-vertex-anthropic"
  || api.id.includes("anthropic") || api.id.includes("claude")
  || id.includes("anthropic")    || id.includes("claude")
  || api.npm === "@ai-sdk/anthropic" || api.npm === "@ai-sdk/alibaba"
```

A provider id of `doubleword` with `npm: "@ai-sdk/openai-compatible"` and models named
`moonshotai/...`, `zai-org/...` or `deepseek-ai/...` matches none of these, so `applyCaching()`
never runs and no cache marker is ever written. `applyCaching()` does contain an
`openaiCompatible` branch, but it is unreachable for this provider. It only fires for a provider
that already passes the gate some other way (a model id containing `claude`, or `@ai-sdk/alibaba`).

Setting `npm: "@ai-sdk/anthropic"` passes the gate. Because `providerID` is still `doubleword`
rather than `anthropic`, opencode takes the content-level branch and attaches
`cache_control: {"type":"ephemeral"}` to the first two system messages and the last two
non-system messages. `@ai-sdk/anthropic` sends `x-api-key` and `anthropic-version` rather than
`Authorization: Bearer`; Doubleword accepts both.

**The key still comes from wherever you already keep it.** opencode resolves the credential
itself (from `options.apiKey`, from a provider `env: [...]` entry, or from a key stored by
`/connect`) and injects it as the SDK's `apiKey` before constructing the client, so switching to
`@ai-sdk/anthropic` does not change how you authenticate. All three forms were verified against
a logging proxy and all three sent a working `x-api-key` and still cached.

**Measured**, running the real opencode CLI (1.18.29) through a logging proxy:

| wiring | markers sent | cold call | warm call |
| --- | --- | --- | --- |
| `@ai-sdk/openai-compatible` | 0 | `cached_tokens: 0` of 7447 | `cached_tokens: 0` of 7462 |
| `@ai-sdk/anthropic` | 2 to 3 per request | `cache_creation_input_tokens: 7407` | `cache_read_input_tokens: 7407` |

Cache reads survive the whole agentic loop, including tool calls and reasoning models that emit
`thinking` blocks (`moonshotai/Kimi-K2.6` multi-turn read 6376 then 6401 tokens).

**Caveats.**
- opencode emits no `ttl`, so every entry uses Doubleword's **5m** default. The 1h TTL is not
  reachable from opencode config today.
- Doubleword does **no** implicit caching. Three identical unmarked `/chat/completions` calls all
  returned `cached_tokens: 0`, so an unmarked request pays full price every time.
- The prefix has to clear roughly a 1,300 token floor before anything is cached.
- Use `deepseek-ai/DeepSeek-V4-Flash` rather than `...-0731` if you test by hand; the dated
  snapshot ignores caching.
- `doubleword-flex` stays on `@ai-sdk/openai-compatible` because `service_tier: flex` is an
  OpenAI-chat-completions concept, so the flex tier gets no caching under the same gate.
- opencode surfaces this per message as `tokens.cache.write` / `tokens.cache.read`
  (visible with `opencode run --format json`).
- **`ANTHROPIC_API_KEY` can mask a missing key.** If no Doubleword credential is resolvable,
  `@ai-sdk/anthropic` falls back to its own `ANTHROPIC_API_KEY` env var, so a user who has one
  exported gets a confusing upstream `APIError` instead of a clean "connect your provider"
  message. A resolvable Doubleword key always wins over it, and this registry pins
  `apiKey: "{env:DOUBLEWORD_API_KEY}"`, so the fallback cannot trigger here. Worth knowing if you
  adapt this config by hand.

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
   - **Cloudflare Workers**: `npm install && npm run deploy` (see below). URL becomes
     `https://doubleword-opencode-ocx.<subdomain>.workers.dev`.
   - **GitHub Pages**: enable Pages for the repo, serving `dist/` (or commit `dist/` to a `gh-pages`
     branch). URL becomes `https://<user>.github.io/<repo>`.
   - **Raw URL**: commit `dist/` and use `https://raw.githubusercontent.com/<user>/<repo>/main/dist`.
   - Or any host (Vercel / Netlify) serving `dist/`.
4. Share: `ocx registry add <that-url> --name dw --global` then `ocx add dw/doubleword --global`.

### Cloudflare Workers (TS port of the Go server)
`src/index.ts` is a Cloudflare Worker equivalent of `main.go`: it serves the built `dist/` via the
Workers static-assets binding (`env.ASSETS`, wired in `wrangler.jsonc`) and logs each request, just
like the Go `http.FileServer`. Cloudflare doesn't run Go natively, so this is the worker-compatible
path.

```bash
npm install

# local dev — serves dist/ on http://localhost:8077 (same as `go run .`)
npm run dev -- --port 8077

# deploy to your Cloudflare account (needs `wrangler login` once)
npm run deploy
```

Then install into opencode against the deployed URL:
```bash
ocx registry add https://doubleword-opencode-ocx.<subdomain>.workers.dev --name dw --global
ocx add dw/doubleword --global
```

Rebuild `dist/` with `ocx build . --out dist` after editing `registry.jsonc` / `files/`, then
re-run `npm run deploy` (or restart `npm run dev`) to serve the new bundle.

## Notes & caveats
- **MCP tool path**: the `doubleword_async` MCP server is launched from
  `{env:HOME}/.config/opencode/tools/doubleword-async/dw_async_mcp.py`. This assumes a **global**
  install at the default config location (`~/.config/opencode`). If you use a custom
  `XDG_CONFIG_HOME` or a project-scoped install, edit the `mcp.doubleword-async.command` path in
  your `opencode.json` to point at the installed script.
- Config-only **flex is the primary path**; the MCP tool is complementary (use it to fire a
  discrete async job from a realtime chat, rather than switching the whole turn to flex).
- Once Doubleword is an official [models.dev](https://models.dev) provider, the realtime provider
  block becomes unnecessary (just a key), and the flex provider + MCP tool remain useful. Keep
  prompt caching in mind when that happens: a models.dev entry registered as an OpenAI-compatible
  provider would fall back outside opencode's caching gate and stop caching. The entry needs
  `npm: "@ai-sdk/anthropic"`, or a provider id / model ids that clear the gate, to keep it.
- The `doubleword_async` MCP tool (`files/mcp/dw_async_mcp.py`) calls
  `/v1/chat/completions` directly with `service_tier: flex` and sends no `cache_control`, so it
  is uncached by design. It fires one-shot prompts with no shared prefix, so there is nothing for
  a cache to hit; leave it as is unless it grows a reused system prompt.

## Repo layout
```
registry.jsonc                       # registry manifest (3 components)
files/mcp/dw_async_mcp.py            # async MCP tool (stdlib only)
files/agent/dw-flex.md               # flex background subagent
dist/                                # built output (generated by `ocx build`)
main.go                              # Go static server that embeds + serves dist/ (Docker path)
go.mod                               # (no dependencies — stdlib only)
Dockerfile                           # self-contained image: docker run -p 8077:8077
docker-compose.yml                   # docker compose up -d --build
src/index.ts                         # Cloudflare Worker port of main.go (serves dist/ via ASSETS)
wrangler.jsonc                       # Worker config: ./dist static-assets binding
package.json / tsconfig.json         # Worker deps + TS config (npm run dev / deploy)
```
