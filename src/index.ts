// Cloudflare Worker port of main.go.
//
// The Go server embedded `dist/` into the binary and served it over HTTP with
// http.FileServer, logging each request. On Workers the file serving is done
// by the native static-assets binding (`env.ASSETS`, wired to ./dist in
// wrangler.jsonc); this Worker just mirrors the request logging and hands off.
//
// `run_worker_first: true` in wrangler.jsonc guarantees this handler runs for
// every request (otherwise a matching asset would be served before the Worker
// is even invoked, and nothing would be logged).

export interface Env {
  ASSETS: Fetcher;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const { method } = request;
    const { pathname } = new URL(request.url);
    console.log(`${method} ${pathname}`);
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;
