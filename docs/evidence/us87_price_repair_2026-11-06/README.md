# US87 price repair — local acceptance, no retraining

PR #1377, frozen producer/next runner `0c8152496ebeeed559ceab9b095594501fca516b`.
Original v5 audit reproduces 9 KLAC and 1 CRWD split-scale events. Corrected v6
was obtained with canonical `refresh_selected_pool_prices --full-refresh`, with
91 exact new Yahoo/yfinance returned frames retained plus the declared governed
EA terminal history. Raw frames reproduce normalization exactly, provider volume
passes through unchanged, and all 92 histories have zero scale anomalies or
unexplained interior gaps. No mechanical scale fix or threshold change was used.

- Independent edition: `us87-cn130-20261103-local-v6-us87-fullrefresh`.
- Manifest SHA256: `4f8225f3c68ee0886b9b707ca140e91dcb509b739b8548fdc10f258574d3da1a`.
- US history ZIP SHA256: `b4745e46fc26b0328e22de50e579ebbf1d400996258ea6ebb43c1ff739ed5a1a`.
- 207 files / 463,622,539 bytes. Offline P2 verification reads all 1,030,712
  Parquet rows, verifies four original domain archives and every bound file.
- US87 candidate rows: 120,401; including five references: 126,671.
  Overall retained US range2021-01-04..2026-11-03; fullUS87+QQQ common292sessions
  2025-06-05..2026-08-04. Actual per-symbol ranges are in `coverage.json`.
- US market evidence/factor series and canonical model-data manifests were
  regenerated from the new source; the US ZIP rebuild reproduces exact bytes.
  The original CN/event/fundamental/Alpha158/professional reference source
  archives remain at their previously frozen versions.
- KLAC10:1 first adjusted trading2026-06-12; CRWD4:1 2026-07-02, confirmed
  against SEC announcements and new provider action columns. Yahoo OHLC with
  auto_adjust=False is already split-adjusted; AdjClose additionally reflects
  dividends. Normalized factor=1 is an adjusted identity, amount is synthetic,
  and provider historical volume is not certified exchange as-traded volume.
- Whole research bundle remains PARTIAL, 5 coverage profiles READY / US Alpha158
  BLOCKED. PIT, snapshot/survivorship, source edition and holdout limits remain.
- Original v5 (200 files) and all 14 checkpoint ZIPs retained exact hashes.
  Completed261-task checkpoint SHA256 remains
  `a760372a8ef8e704ec428b77a66598451de9e3095bc2a1461acc9063129e8219`.
- The new private Colab job has a new data/batch/run identity and checkpoint
  parent. All model/feature/parameter/seed/fold/cost choices are unchanged.
  Training defaults OFF. No local research fit, Colab execution or PR merge.

Files here are manifests, aggregate coverage and acceptance metadata, not raw
market data or checkpoints. Exact raw Yahoo frames and canonical CSVs remain
inside the private new US producer source archive. Owner's existing cloud rights
attestation is rebound to exact v6 hashes, not independently vendor-certified;
original dataset approval flags stay false. Remote Drive sync and ACL acceptance
are not implied by filesystem readback.


Drive Desktop delivery passed strict size/SHA readback for all207datasetfiles
and8owner-jobfiles. Root `AlphaEngine/运行模型探索.ipynb` now selects v6 with
trainingOFF. Its previous Owner-edited version was saved privately before
replacement; the original 261-task checkpoint remains untouched. Delivery
summary and root/notebook hashes are in `drive-delivery.json`. Google Drive
remote synchronization and private ACLs were not independently inspected.
