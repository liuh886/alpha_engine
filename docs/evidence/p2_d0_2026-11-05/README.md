# P2-D0 physical evidence — 2026-11-05

Current verdict: **PARTIAL**. Immutable **v5** contains **200 files / 452,928,235 bytes**; producer code `32c30ef05258a35e4300b6a21ea7a96d0dab17cf`. Bundle Manifest SHA256: `d9f4fb2ef7aa2735cfb95436e7eabb744ffb8d6d387c4294626893fc262dab0c`.

The existing model-data contract is unchanged (`a4f7d3e352adcd994e74e1152e27a9a241ea307c04578b6f1ca2258fa81b7ac5`). Its six selected-pool coverage gates are reconstructed from exact archived manifests and verified physical payloads, rather than copied READY labels.

| Existing profile | Physical coverage gate | Disclosed source cutoffs |
| --- | --- | --- |
| US87 price only | READY | prices 2026-11-03 |
| CN130 price only | READY | prices 2026-11-03 |
| US87 price + fundamentals/actions | READY under existing >=80% fundamental threshold | events 2026-09-30; prices 2026-11-03 |
| CN130 price + fundamentals/actions | READY under existing >=80% fundamental threshold | events 2026-09-04; prices 2026-11-03 |
| CN130 Alpha158 | READY under existing declared not-yet-applicable partition | factors 2026-09-04; prices 2026-11-03 |
| US87 Alpha158 | BLOCKED: canonical factor component absent | genuine VWAP/SIP/OTC entitlement unavailable; Owner asked to retain blocker |

READY applies only to the existing coverage contract at these editions. It does not certify all history/fields, current freshness, PIT, training permission, labels/costs or a custom study. CN 301666 remains one retained short-history panel: 129/158 factor-quality rows ready, 29 blocked; it is not deleted or filled. Canonical fundamentals remain US86/87 and CN127/130; separate CN supplements retain 96/18/138 events for 301309/301666/600276 without source promotion. SEC SBGSY remains unsupported.

- `profile-readiness-v5.json`: actual six-profile results, exact physical evidence hashes and independent source cutoffs. The CSI300 registry now explicitly includes the existing bare provider alias `000300` for canonical index `000300.SH`; no index/ETF substitution.
- `package-manifest-v5.json`: complete v5 file/size/SHA inventory, original domain/source identities, normalized components and retained limits. No raw price/event/factor values are committed.
- `offline-acceptance-v5.json`: fresh frozen checkout, socket connects denied, all Parquet pages readable, exact original/panel/CSV parity including NaNs, inventory reproduction and 1,119 text payload privacy checks.
- `cn-session-gap-review.json` and `cn-session-review-manifest.json`: separately sealed retrospective classification of all **85 interior absent CN sessions across 11 symbols / 14 suspension intervals**, using **16 primary issuer PDFs**, MinerU 4.1.3 local extraction, manual start/resume review and exact XSHG session-set equality. Zero bars added or symbols removed. This explains interior absences only; source-history prefixes and PIT remain unverified. The original frozen audit is unchanged.
- `delivery-index-v5.json`: binds v5, the suspension review ZIP, offline acceptance and Owner-directed transfer receipt. Review ZIP: **3,902,212 bytes**, SHA256 `79b15366beb69cfbaf974a1d2fe2d9cf31237df3959e3ce9d6369590d58a8b01`.
- `drive-desktop-save-receipt-v5.json` / `rights-and-drive-status.json`: all 200 v5 files plus supplemental evidence saved to the existing private automatic-sync directory, sizes/SHA read back successfully. Remote synchronization, remote ACL and downloaded cloud-byte parity are not independently verified. Owner authorization persists; frozen producer approval flags remain unchanged.
- `symbol-coverage.csv` / `adjustment-and-event-validation.json`: all 229 instruments' observed dates/rows and source semantics. US87 has 116,433 candidate rows; CN130 has 174,583; observed overall range 2021-01-04–2026-11-03, with varying starts and terminal dates. Latest factor=1 placeholders are not certified adjustment ratios; latest VWAP absent, Tencent volume remains provider_reported, CN amount has 93 nulls; action pay dates/announcement vintage and reference editions remain qualified.

Validation: **92 focused tests PASS**, Ruff PASS, Mypy PASS on the new readiness and aggregate modules. Both v5 market-history ZIPs are separately rebuilt from frozen inputs for byte parity. Prior v4 evidence files remain historical; v4 is preserved unchanged. No Colab, strategy execution, frontend change, raw-data Git commit, synthetic fill, threshold reduction or PIT certification.
