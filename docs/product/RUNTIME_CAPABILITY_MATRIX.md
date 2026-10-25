# Research Studio Runtime Capability Matrix

> **HISTORICAL / SUPERSEDED — 2026-10-25 (#1278).** The matrix, hard rules,
> release gates and rollback steps below describe the retired Research Studio.
> In particular `/system` is now maintained Operating Status; current account
> authorization remains enforced, while local ZIP readers, connected browser
> research and offline installation are retired. Do not implement or restore
> them from this document. Use [AGENTS.md](../../AGENTS.md), the
> [current product / local Agent handoff](strategy_console.md#local-agent-start-here),
> [access contract](../architecture/frontend_access_control.md) and
> [operating recovery runbook](../operations/decision_loop_recovery_2026-10-03.md).
> Historical instructions below are retained for audit only.

| Capability | Published Pages/PWA | Local artifact | Connected research |
|---|---:|---:|---:|
| Authentication | No | No | Required |
| Published bundle | Read | Read | Read |
| Local directory / ZIP | Read | Read | Read |
| FastAPI reads | No | No | Yes |
| Jobs and polling | No | No | Yes |
| Data refresh | No | No | Yes |
| Model deletion/promotion | No | No | Yes |
| System and agent operations | No | No | Yes |
| Offline application shell | Yes | Yes | No guarantee |
| Recent bundle metadata | IndexedDB | IndexedDB | IndexedDB |
| Reusable directory handle | Browser-dependent | Browser-dependent | Browser-dependent |

## Hard rules

1. Static and local modes never register connected-only routes. Typing `/system`, `/agent`, `/backtest` or another developer route manually must land on the runtime-safe not-found page.
2. Static and local modes do not authenticate, poll jobs, refresh data, mutate models or invoke system operations.
3. Missing local/static evidence is never replaced by connected evidence automatically.
4. The browser reads selected local files in place. GitHub Pages receives no selected bundle bytes or local paths.
5. Connected operations remain authenticated and deliberately separated under Developer navigation.

## Automated release gates

The `Frontend Static PWA` workflow blocks merge on:

- TypeScript and ESLint;
- frontend unit tests;
- production static build;
- PWA manifest, service worker and icon presence;
- existing bundle-size budget;
- Chromium browser acceptance at desktop, tablet and mobile sizes;
- no authentication wall and no `/api/*` request in static mode;
- artifact-native Data navigation;
- manual connected-route rejection;
- visible keyboard focus and horizontal-overflow check;
- first-visit service-worker readiness and offline shell reload;
- screenshot and trace artifact upload.

## Screenshot review

CI saves deterministic screenshots for desktop, tablet and mobile under the `alpha-engine-static-browser-evidence` artifact. These are implementation evidence and should be reviewed before major visual releases. Automated screenshots do not by themselves prove complete accessibility or visual quality.

## Rollback

If a release regresses Pages/PWA:

1. revert the offending frontend merge commit;
2. let `pages.yml` rebuild from the reverted `main`;
3. rotate the application version if the service-worker cache contract changed;
4. verify the published bundle and offline shell with the static browser workflow.
