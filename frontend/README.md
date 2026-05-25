# CAP Frontend

Svelte single-page app that fronts the CAP HTTP API. See `SPEC.md` for
the full design.

## Development

```bash
npm ci
npm run dev        # http://localhost:5173 with /api proxied to :8085
npm run check      # svelte-check type pass
npm run build      # outputs static bundle to ./dist
npm run preview    # serve ./dist for a sanity check
```

## Runtime config

`public/config.js` is loaded by `index.html` before the bundle. Edit
it in place on a deployed instance to change the API base URL,
override the OAuth login URL, or rename the product. Defaults are
applied by `src/lib/config.ts` if the file is missing.

## Deploy

```bash
npm run build
# ship ./dist behind a reverse proxy:
#   /api/* -> backend (strip /api prefix)
#   /*     -> dist/
#   404    -> dist/index.html  (SPA fallback for hash routing)
```

## AI-assisted development

This application was developed using AI-assisted technology. The
inputs provided to the AI consist of copyleft and/or fair-use of
publicly available material, together with direct human input and
guidance. The resulting output (the source code in this repository)
is licensed under the Apache License, Version 2.0. See the
[`LICENSE`](../LICENSE) file at the repository root for the full text.
