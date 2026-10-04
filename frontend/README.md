# Demo UI (React + TypeScript + Vite)

The web front end for `../demo`. It talks to `../demo/server.py`, which runs the demo scripts and serves this app's build.

```bash
npm install        # once
npm run dev        # http://localhost:5173, proxies /api and /results to the Python server on :8765
npm run build      # type-check + production build into dist/ (served by server.py)
```

- **Nothing loads from the internet at runtime.** System fonts only, no CDN, no chart library; the charts are hand-built SVG in `src/components/charts.tsx`.
- **Colours** come from the validated data-viz reference palette, with light and dark themes each defined in `src/styles.css`.
- **Types** in `src/api.ts` mirror the JSON written by the demo scripts.
- **Panels** live in `src/panels/` (one per demo A–E). The on-screen wording follows `../02_Demo_Plan_Tomorrow.md` §3 and the caveats in `../demo/README.md`.
