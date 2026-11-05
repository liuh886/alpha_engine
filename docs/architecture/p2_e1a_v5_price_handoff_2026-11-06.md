# P2-E1-A — v5 price-domain cloud handoff and independent verification

**Decision (2026-11-06):** E1-A is allowed to progress **only** on the complete governed **US87 daily-price** domain, independently of the genuinely BLOCKED US Alpha158 input. This does not promote the six-profile overall `PARTIAL` status, and it does not authorize model execution or live trades. #1370 continues as a separate research-breadth task. Owner runs the trusted Colab session only after per-provider cloud-processing rights and exact recipe execution are actually reviewed.

## Independently completed without the local Agent

Connected Google Drive was queried at the **server**, not via Drive Desktop:
- v5 folder exists under private `Research_Exchange_P2/input_packages`; recursively enumerated **200 cloud files**, exactly **452,928,235 bytes** by cloud-reported sizes. Parent/v5 folder permission metadata shows only an owner grant; enumerated children were not shared.
- Fetched exact remote `bundle-manifest.json`, 577,433 bytes; independently computed SHA256 `d9f4fb2ef7aa2735cfb95436e7eabb744ffb8d6d387c4294626893fc262dab0c`.
- **Downloaded** remote `us_market_history.zip`, 15,492,777 bytes; SHA256 `93b2d42cebf3ebfac7b80298f6822fdc4305f7550b73ac1b2bb8d272d3fb3de8`. Its **106 internal files** independently pass per-member SHA256/size; no extra/missing members; CRC PASS.
- **Downloaded** remote `cn_market_history.zip`, 39,286,318 bytes; SHA256 `252451348c97ae166a2df6accbccad137ac673c34c5e7fdb50d0227c2023670e`. Its **151 internal files** independently pass per-member SHA256/size; CRC PASS.
- Downloaded remote `normalized/us_prices.parquet` (4,016,855 bytes), SHA256 `ec82de9efa600f01e78b7838023b2d3bb4c4c89cf02516bfb560e6aa56c0c7c3`, and `normalized/cn_prices.parquet` (5,878,552 bytes), SHA256 `1bdee490ae174a723c615b5aa52fce7c92f3ce858412429032fb98210825cb4f`.

**Boundary:** these data inputs plus root Manifest have independent cloud-byte parity; the OTHER cloud files have only inventory/size verification or local Drive Desktop readback (not an independent remote SHA check). The integrity proof is not vendor permission, PIT certification or a real Colab run. The frozen original v5 bundle remains unchanged.

## Critical old-Notebook incompatibility

The old `notebooks/colab_research_exchange_pilot.ipynb` expects `alpha_research_exchange_v1` and calls `cloud_exchange.verify/stage`. **v5 actually contains `p2_local_market_history_v1`** with `data_only=true`, `transfer_scope=local_only`, `owner_approved_private_cloud_copy=false`. Its candidate/canonical source files have been data-only projected and must not overwrite matching original files in the producer checkout. Do not hack its manifest version or flip those original producer flags.

**Implemented replacement**:
- `src/research/e1a_price_preflight.py`: checks pinned v5 root + US archive SHA, roster/cutoff/source-producer identity, and reuses `comprehensive_bundle.verify_local_history` (all internal SHA/size/roles and data-only fields). A missing rights record yields `BLOCKED_NO_PER_SOURCE_CLOUD_RIGHTS_RECORD`, not automatic approval. `--require-cloud-rights` returns nonzero until a separate, provider-specific operator record is present. The returned output ALWAYS preserves `model_execution_authorized=false`, `pit_certified=false`, `trade_ready=false`.
- `notebooks/colab_v5_price_preflight.ipynb`: owner-run, default opt-in FALSE; mounts private Drive, checks separate rights record BEFORE copying market data, copies exactly root Manifest + US87 history ZIP once to Colab scratch, hashes them externally, pins an exact Git verifier revision, invokes `e1a_price_preflight` without staging/overwriting frozen original data. **It stops before a study**; there is no auto return/upload/publish.

The **source producer revision** is `32c30ef05258a35e4300b6a21ea7a96d0dab17cf`. The **preflight verifier revision** should be set to a subsequently CI-green exact PR #1368 SHA that contains the new code. An actual study experiment revision must be pinned separately and identical between local and Colab; do not assume these three revisions have the same meaning.

### Local input validation command (no cloud rights assumed)

Run from PR #1368 branch, with the real synced v5 directory, replacing the private path:

```bash
uv run --frozen python -m src.research.e1a_price_preflight \
  --manifest "<private-v5>/bundle-manifest.json" \
  --archive "<private-v5>/us_market_history.zip" \
  --expected-manifest-sha256 d9f4fb2ef7aa2735cfb95436e7eabb744ffb8d6d387c4294626893fc262dab0c \
  --expected-archive-sha256 93b2d42cebf3ebfac7b80298f6822fdc4305f7550b73ac1b2bb8d272d3fb3de8
```

Expected: verified data and `BLOCKED_NO_PER_SOURCE_CLOUD_RIGHTS_RECORD`. For a later cloud session pass `--rights-record <private-file> --require-cloud-rights`. The rights JSON (never committed) must use `e1a_price_cloud_rights_v1`; bind exact market=`us`, both SHA256s, purpose=`private_colab_daily_price_research`, operator approval=true, reviewed_at, and for **each actual provider** a `provider_rights` entry with provider, terms_url, explicit review_basis and `private_cloud_compute_permitted=true` if supported by the actual rights. Merely writing these fields is **not** independent proof of vendor permission.

### Provider and Colab rights review: pending external decision

Source usage/transfer terms and cloud processing rights are **separate from public data availability**.

| Source | Current qualified conclusion | Source to review |
| --- | --- | --- |
| Yahoo/yfinance market history and ETF reference | Private owner copying attested; no independently substantiated provider approval for transferring historic vendor data into third-party Colab compute. **BLOCKED_PENDING_SOURCE_TERMS** | https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html |
| Tencent price/qfq, Sina/CNINFO/Eastmoney selected CN components | Individual terms and data-processing rights not independently established; CN scope stays separate from US E1-A. | Actual provider terms linked in existing source receipts / provider configuration |
| SEC EDGAR filings | Official public APIs exist (with fair access limits); nevertheless exact use case must obey site/publisher conditions and version timing. | https://www.sec.gov/search-filings/edgar-application-programming-interfaces |
| Google Colab | Colab terms place responsibility for compliance with third-party licenses on the user; Google permission to run a notebook is not a financial-data vendor license. | https://research.google.com/colaboratory/tos_v5.html |

DO NOT assert that Yahoo/yfinance permits a private Colab copy on the basis of this review. If provider terms do not allow the intended cloud processing or the user's precise entitlement remains uncertain, keep cloud execution blocked and run locally; a legally licensed alternate edition requires its own *new* source manifest, hashes and research review, never silent substitution.

## Local Agent: actual implementation handoff, no duplication

1. On latest PR #1368, run the new **local preflight** against synced immutable v5 and its pinned hashes. Test that missing or mismatched rights, wrong repository revision, tampered archive and false cloud entitlements all fail closed. Leave original 200 files untouched.
2. Inspect **actual** `src/cli/main.py` / `src/research/study_workspace.py` and select the *existing runnable* US87 **price-only** study that does not require true VWAP, fund/events or a missing PIT label. Confirm its CLI entrypoint (do not rely on the old notebook's unverified string), frozen experiment spec, price-basis, benchmark QQQ, calendar, costs, seed, lookback and actual minimum overlap. If no such runner exists, implement **the thinnest input adapter** from the frozen v5 archive to an existing research study rather than a second engine/database.
3. Run the chosen existing daily-price study locally with **v5 as its data authority**, record exact experiment code SHA, package hash, research metrics and output hash/tolerance. Distinguish source snapshot, optimizer input, target labels and cutoff; do not call training-profile READY a PIT proof.
4. Resolve actual provider terms or obtain a rights-cleared new source edition, then create the private bounded rights record; do not falsely mark `owner_approved_private_cloud_copy` on immutable v5. Owner explicitly opts in to run the **new** v5 Notebook from a reviewed pinned commit; not before.
5. Run Colab with the *same experiment code/spec/data* as local, record CPU/RAM/runtime and local-vs-Colab output parity, keep returns in `incoming_unreviewed`, perform local independent review. Do not run orders, update public Pages, or start US Alpha158. Record result in #1369; #1370 remains PARTIAL.

**Release discipline:** targeted tests + existing CI, no broad new tests/data pipelines. PR #1368 remains Draft until E1-A real operation is proven or scope is split appropriately.
