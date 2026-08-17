# Alpha Engine frontend access control

## Product contract

Alpha Engine has four monotonic product levels: `public`, `authenticated`, `pro`, and `owner`. Owner inherits Pro; Pro inherits authenticated and public access. Account tier is never inferred from a model family.

The product has two deliberately different publication boundaries:

- **Formal historical research evidence is public.** Retained backtests, benchmarks, performance and risk evidence published under the GitHub Pages formal catalog are designed to be inspectable without payment. The product must not describe those static artifacts as confidential or Pro-exclusive.
- **Current strategy operations are the paid boundary.** Current holdings, target allocations, current signals and next-decision state are read from Supabase-backed strategy operation resources. Their minimum tier is resolved from `product_access_policies`, and access to protected rows is enforced at the Supabase/RLS boundary, including the `alpha_engine.pro` entitlement. React gates mirror that policy for navigation and presentation; they are not the security authority.

This is the canonical product positioning: **public evidence earns trust; Pro unlocks current operational decision surfaces.**

## Policy resources

`product_access_policies` stores minimum tiers for two resource types:

- `strategy` — keyed by stable `strategy_id` for current operation snapshots;
- `module` — keyed by a declared frontend module resource ID.

Owner changes policy rows from `/settings/access`. Browser defaults are fail-safe only while Supabase policy state is loading or unavailable; they do not create a second writable policy authority.

## Supabase boundary

Policy writes require an authenticated JWT whose server-controlled `app_metadata.alpha_engine_role` is `owner`. Strategy operation reads are split by tier in RLS: public/authenticated rows can be selected at their declared tier, while Pro/Owner rows require the corresponding entitlement/role. Never place service-role credentials in browser assets or this repository.

## Static deployment boundary

GitHub Pages serves the formal historical catalog as public static files by design. UI gating of those static URLs is a reading affordance, not confidentiality. If a future product decision makes a historical artifact genuinely private, that artifact must leave GitHub Pages and move behind an authenticated transport/RLS boundary before the product claims exclusivity. Until such a decision exists, no duplicate private copy or migration path should be maintained.
