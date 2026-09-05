# CN governed source refresh through 2026-09-04

Research only; `research_only=true`, `trade_ready=false`. This advances source
evidence, not model parameters, selected membership or training approval.

## Accepted evidence

- Canonical VWAP / Alpha158: [run 33940840760](https://github.com/liuh886/alpha_engine/actions/runs/33940840760), artifact 9961938297.
- Selected-pool events: [run 33942729365](https://github.com/liuh886/alpha_engine/actions/runs/33942729365), artifact 9962408566.
- Both runs succeeded on main SHA `793aa7be12951ce7e8877f2c59861789cccf1839`.
- Both archives were downloaded and checked against GitHub's exact SHA256 and
  byte size, safely extracted, and passed the existing full-tree source
  verifiers before registry rebinding. The registry pins all component hashes.
- CN Alpha158 passes its ready-profile verifier. Corporate actions report
  coverage for all 130 selected names. Fundamentals remain **partial**, 129/130,
  with the existing `301666` provider gap retained. This does not open the
  blocked fundamental-dependent training gates.

## Retained failure and recovery

The first event build, [run 33940838575](https://github.com/liuh886/alpha_engine/actions/runs/33940838575), succeeded as an evidence-producing workflow but had only
123/130 fundamental coverage. It was **not** adopted as the formal source.

- Artifact: 9962017106; archive SHA256:
  `05594c45061266a476852ef5aeda5a7eb8c708fd94b2d770d0d9719e1a26188c`.
- Event manifest SHA256:
  `0ce84f1003b668e0498f03997a1973e7981200919e504d28cb702504f5efc7a9`.
- New failures: `000063`, `000895`, `000938`, `000963`, `000977`, `002648`;
  all recorded CNINFO JSON decoding errors. `301666` remained the prior gap.
- Rerunning the same frozen cutoff reused verified exact-cutoff source lanes,
  preserved their retrieval times, and fetched missing lanes. Coverage returned
  to 129/130 without older-date fills, membership changes or source substitution.

Raw failed and accepted artifacts remain under their original run identities
and retention policies. This committed record preserves the failure after their
retention ends; it does not claim to preserve the raw archives indefinitely.

## Publication boundary and remaining debt

The reviewed formal-refresh transaction must consume these registry bindings,
regenerate the shared bundle and frontend projections, and pass candidate and
release checks before the dashboard can be described as updated. Merely changing
this registry is not evidence of a completed frontend deployment.

Source role names are stable (`cn_alpha158`, `cn_events`); identities remain
review-bound, never discovered as arbitrary latest-successful artifacts.
Artifact retention is still finite (2026-12-04 for these sources). A reviewed
regeneration/rebinding path remains necessary before expiry. US SEC egress and
US canonical VWAP credentials remain separate unresolved external dependencies.
