# Demo UI (React + TypeScript + Vite)

The web front end for `../demo`. It talks to `../demo/server.py`, which runs the demo scripts and serves this app's build.

```bash
npm ci             # once (installs exactly what package-lock.json pins)
npm run dev        # http://localhost:5173, proxies /api and /results to the Python server on :8765
npm run typecheck  # tsc only
npm run build      # type-check + production build into dist/ (served by server.py)
```

- **`dist/` is committed** so the demo runs without Node. Rebuild and commit it after every UI change.
- **Nothing loads from the internet at runtime.** The fonts (Bricolage Grotesque, Instrument Sans, JetBrains Mono) are bundled from Fontsource, there's no CDN and no chart library; the charts are hand-built SVG/CSS. Check a build with `python scripts/check_offline_build.py frontend/dist` from the repo root.
- **Design** is the "Cocoa Pop" system from the design canvas (brown, beige and white, springy motion). Tokens and the demo's components are in `src/styles.css`; the canvas kit (landing, app shell, page pieces) is in `src/design.css`. The Motion toggle adds `still` to `<html>` to stop the animations.
- **Types** are the shared API contract in `../contract/types.ts`. `src/api.ts` imports them (`import type … from "../../contract/types"`) and re-exports them, so the rest of the app imports types from `./api`. `tsconfig.json` includes `../contract` for this. Don't redeclare response types in `src/`.
- **API client** is `src/api.ts`: fetch helpers, and `followJob`, which streams a job's output and falls back to polling if the stream breaks.
- **Step catalogue** (labels, durations, confirmation texts) comes from `GET /api/steps` at load; `src/steps.ts` holds the fallback used only if that request fails.
- **Staleness** (UI_INTEGRATION.md §7) is decided in one place, `src/stale.ts`, for both the sidebar and the panels.
- **Routes** use a tiny history-API router (`src/router.tsx`); `server.py` returns `index.html` for unknown paths, so deep links survive a reload.

  | Path | File |
  |---|---|
  | `/` | `src/pages/Landing.tsx` (no app shell) |
  | `/app` | `src/pages/Overview.tsx` |
  | `/app/embed` | `src/pages/Embed.tsx` |
  | `/app/verify` | `src/pages/Verify.tsx` (reads `/results/protocol_v2/{proof,public,onchain}.json`) |
  | `/app/robustness` | `src/pages/Robustness.tsx` |
  | `/app/demo/A`…`F` | `src/pages/Demos.tsx`, which renders the research panels in `src/panels/` (← → move between them) |

  The sidebar is `src/shell/Side.tsx`; icons and the logo are `src/components/icons.tsx`. Each page and the console sit in their own error boundary (`src/components/ErrorBoundary.tsx`). The panel wording follows the caveats in `../demo/README.md`.
