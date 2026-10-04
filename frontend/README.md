# Demo UI (React + TypeScript + Vite)

The web front end for `../demo`. It talks to `../demo/server.py`, which runs the demo scripts and serves this app's build.

```bash
npm ci             # once (installs exactly what package-lock.json pins)
npm run dev        # http://localhost:5173, proxies /api and /results to the Python server on :8765
npm run typecheck  # tsc only
npm run build      # type-check + production build into dist/ (served by server.py)
```

- **`dist/` is committed** so the demo runs without Node. Rebuild and commit it after every UI change.
- **Nothing loads from the internet at runtime.** System fonts only, no CDN, no chart library; the charts are hand-built SVG in `src/components/charts.tsx`. Check a build with `python scripts/check_offline_build.py frontend/dist` from the repo root.
- **Colours** come from the validated data-viz reference palette, with light and dark themes each defined in `src/styles.css`.
- **Types** are the shared API contract in `../contract/types.ts`. `src/api.ts` imports them (`import type … from "../../contract/types"`) and re-exports them, so the rest of the app imports types from `./api`. `tsconfig.json` includes `../contract` for this. Don't redeclare response types in `src/`.
- **API client** is `src/api.ts`: fetch helpers, and `followJob`, which streams a job's output and falls back to polling if the stream breaks.
- **Step catalogue** (labels, durations, confirmation texts) comes from `GET /api/steps` at load; `src/steps.ts` holds the fallback used only if that request fails.
- **Staleness** (UI_INTEGRATION.md §7) is decided in one place, `src/stale.ts`, for both the sidebar and the panels.
- **Panels** live in `src/panels/` (one per demo A–E), each wrapped in an error boundary (`src/components/ErrorBoundary.tsx`). The on-screen wording follows `../02_Demo_Plan_Tomorrow.md` §3 and the caveats in `../demo/README.md`.
