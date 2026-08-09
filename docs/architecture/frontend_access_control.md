# Alpha Engine frontend access control

## Contract

Alpha Engine uses four monotonic product levels:

1. `public` — no sign-in required;
2. `authenticated` — any signed-in account;
3. `pro` — an active `alpha_engine.pro` entitlement;
4. `owner` — verified `app_metadata.alpha_engine_role=owner`.

Owner inherits Pro, Member and Guest access. Pro inherits Member and Guest
access. A model family does not imply an account role. `qqq_rotation=pro` is an
initial policy row that Owner may change, not a conditional in application code.

## Policy resources

`product_access_policies` stores the minimum tier for two resource types:

- `model`: keyed by stable `model_family_id`;
- `module`: keyed by the declared frontend module resource ID.

Initial policy:

| Resource | Minimum tier |
| --- | --- |
| `model:qqq_rotation` | `pro` |
| `module:securities` | `authenticated` |

The application keeps the same initial policy as a fail-safe while Supabase is
loading or unavailable. A successfully loaded database row overrides the
fail-safe. Owner changes are made from `/settings/access`.

## Supabase boundary

The migration in `supabase/migrations` creates the policy table, explicitly
grants Data API access, enables RLS, and allows public policy reads. Only an
authenticated JWT whose server-controlled `app_metadata.alpha_engine_role` is
`owner` may insert, update or delete Alpha Engine policy rows. Writes must bind
`updated_by` to `auth.uid()`.

Provision the Owner role with the Supabase Admin API or Dashboard. Never place a
service-role key in this repository or set Owner through `user_metadata`. After
changing app metadata, refresh the user's session so the new JWT claim is
present.

## Deployment boundary

The current GitHub Pages deployment publishes research JSON as static assets.
The access layer prevents unauthorized display and prevents gated React pages
from fetching evidence, but it is not server-side confidentiality for those
static URLs. If protected artifacts must be non-public at the transport layer,
move them to private Supabase Storage or an authenticated API and enforce the
same tier policy with RLS before claiming data-level protection.
