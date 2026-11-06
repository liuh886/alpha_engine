# P2-E2 local execution and manual Colab deployment

Status: **LOCAL_ACCEPTED_OWNER_RUN_READY**. Colab: **NOT_RUN**; Owner explicitly
will access Colab personally. This evidence does not certify cloud runtime,
vendor licensing, PIT, untouched-test performance, GPU gain or a released model.

- `local-training-acceptance.json`: actual final-code full-US87 training, sampled
  local environment/runtime/RSS, fresh-directory checkpoint restore, unchanged
  completed evidence and matching local Notebook/CLI study hash. Two final CLI
  trials each had 120 training sessions / 10,440 rows and 61 validation sessions.
- `owner-run-deployment-manifest.json`: exact hashes of the seven private Owner
  deployment files. Actual notebook, rights declaration and paths remain private;
  no raw market data or model weights are committed here.

Runner: `79e1045bf3ed99bab13ef092cbb07af6ebbf8d99`; producer:
`32c30ef05258a35e4300b6a21ea7a96d0dab17cf`. Original v5 Manifest SHA remains
`d9f4fb2ef7aa2735cfb95436e7eabb744ffb8d6d387c4294626893fc262dab0c`.
Actual source intersection is 292 US87+QQQ sessions, 2025-06-05–2026-08-04.
US Alpha158 remains BLOCKED; this batch uses existing price-derived features.

Manual-run deployment: **7 files / 30,201 bytes**, saved to the existing Drive
Desktop exchange `colab_jobs/us87-validation-79e1045bf3`, each size/SHA read back.
Private Notebook has paths, source/spec/rights/code pins and Owner-requested
manual-run opt-ins configured. Default chunk is two trials; the frozen example
plans 16 validation trials. Public template remains opt-in disabled. Checkpoints
are immutable, bounded to 20 MiB, source-bound and `incoming_unreviewed`.

Owner explicitly attested existing private cloud-compute permission. The
documentary proof location has not been supplied and is not invented; this is
not independent vendor certification. Original data approval flags remain
unchanged. No remote sync/ACL/cloud-byte acceptance is asserted.

52 focused regressions, Ruff and Mypy pass. Backend, Policy and GitGuardian pass
at the frozen runner. Local Notebook flow executed with local mount/bootstrap
substitutions, rendered to HTML and visually inspected. Actual Colab execution,
cross-platform numerical comparison and cloud resource benefit await the Owner.


## Later multi-model preparation (PR #1376)

The preceding seven-file/16-task deployment remains immutable. The new
**LOCAL_ACCEPTED_OWNER_RUN_READY** deployment uses frozen runner
`b3764bab1a4eb694e302053db16426de2e3573fb`, stacked on #1374.

- `model-exploration-local-acceptance.json`: actual three-family local pilot,
  ZIP checkpoint restored into fresh outputs (one retained task skipped, two
  real models fitted), 107 regressions and matching local notebook/CLI study
  hashes. Each trained model had 114 effective train sessions / 9,918 row-symbol
  observations and 39 validation sessions. Actual figures/table rendered and
  inspected; local mount and clone/install bootstrap were substituted.
- `model-exploration-deployment-manifest.json`: seven content files plus this
  hashed deployment manifest, **8 files / 55,447 bytes**, in private Drive
  Desktop `colab_jobs/us87-exploration-b3764bab1a`. No raw data is included.
- `model-exploration-drive-readback.json`: byte/size readback and manifest SHA
  `d73cf9ffb3d5491a626b58487055ba82a3b292e72c701a38a631e33cb65e11d7`.
  Remote Drive synchronization/ACL acceptance remains unverified.

The owner-run example compiles 29 configurations / 261 fold-seed tasks (252 ML
fits, 9 deterministic rule tasks): 24 pre-sampled hyperparameter configurations,
three validation folds × three seeds, controlled feature ablations and cost
stress. Default chunks start at most six tasks / 300 seconds; a native fit can
finish after that start deadline. Single-ZIP export/restore pins both archive
and index hashes and retains the existing 20 MiB uncompressed receipt budget.
No final holdout is scored, no result is promoted and no broad sweep ran locally.

XGBoost/LightGBM use their existing native CPU adapters; the momentum comparator
uses the same source and portfolio simulator. These are existing OHLCV features,
not US Alpha158. All US87+QQQ share only 292 sessions; increasing trial count does
not add independent history. July 1–August 4, 2026 is excluded from this search;
prior use by other research is NOT_CERTIFIED. Optuna/Bayesian pruning, neural
architectures, GPU gain, actual Colab execution and remote parity are NOT_RUN or
not implemented. Owner rights attestation remains distinct from documentary
vendor proof. Backend/Policy/GitGuardian passed at the frozen runner.


## Current Drive root entry (Owner relocation)

Owner requested moving AlphaEngine directly into Drive root. Use
`AlphaEngine/运行模型探索.ipynb`; its paired current job is
`AlphaEngine/03_Data/Research_Exchange_P2/colab_jobs/us87-exploration-root`.
The basic version is `us87-validation-root`. Prior deployment summaries above
remain historical and their original bytes are retained. See
`drive-root-relocation.json`, `us87-exploration-root-deployment-manifest.json`
and `us87-validation-root-deployment-manifest.json`. All 435 ordinary original
files retained SHA256s; seven native Drive virtual pointers retained relative
paths/lengths. Current notebook/configuration paths and source/spec/rights hashes
were validated without new model training or Colab access. Remote sync and ACL
verification remain outstanding.
