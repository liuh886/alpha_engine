# A-Share Structured Pool v1 Freeze Record

Date: 2026-07-30  
Issue: #214

## Decision

`cn_small_pool_v1_frozen`

The user approved the compiled 21-security A-share pool, its six primary economic baskets, CSI 300 as the market-regime and performance benchmark, and ChiNext as an informational growth-style context before any pool performance result was viewed.

## Frozen identity

- pool: `configs/pools/cn_small_pool_v1.yaml`
- research contract: `configs/research_paradigms/cn_small_pool_sector_rotation_v1.yaml`
- market: China A-share
- candidates: 21
- baskets: 6
- benchmark: CSI 300 `000300.SH`
- style context: ChiNext `399006.SZ`
- primary basket per candidate: exactly one
- performance authority: enabled for the frozen contract only

## Frozen baskets

### Semiconductor, storage, and electronic manufacturing

- 澜起科技 `688008.SH`
- 通富微电 `002156.SZ`
- 深科技 `000021.SZ`
- 佰维存储 `688525.SH`
- 卓胜微 `300782.SZ`

### PCB, optical communication, and connectivity

- 沪电股份 `002463.SZ`
- 光迅科技 `002281.SZ`
- 长芯博创 `300548.SZ`
- 中天科技 `600522.SH`

### Data-center power and thermal management

- 金盘科技 `688676.SH`
- 英维克 `002837.SZ`

### New-energy materials, solar, and chemicals

- 天赐材料 `002709.SZ`
- 隆基绿能 `601012.SH`
- 华鲁恒升 `600426.SH`

### Metals, resources, and energy shipping

- 紫金矿业 `601899.SH`
- 中国铝业 `601600.SH`
- 中远海能 `600026.SH`
- 招商轮船 `601872.SH`

### Advanced manufacturing, automotive, and high-end equipment

- 比亚迪 `002594.SZ`
- 三环集团 `300408.SZ`
- 中国船舶 `600150.SH`

## Point-in-time eligibility boundary

The pool freezes membership and primary basket assignment. It does not invent static listing eligibility, suspension, ST, delisting, or price-limit history.

Issue #216 must obtain these fields from a manifest-bound point-in-time provider before authoritative validation:

- verified first eligible trading date;
- suspension and tradability flags;
- point-in-time ST and delisting status;
- price-limit state at the assumed execution point;
- consistent corporate-action adjustment convention.

A missing or non-tradable security remains in the frozen membership record and fails closed for new entries. It is not silently removed.

## Governance after freeze

- any addition, removal, alias change, or basket reassignment requires `cn_small_pool_v2`;
- weak observed results cannot justify retroactive removal from v1;
- short-history securities remain explicit;
- US and CN cross-sections remain separate;
- no 2026H2 performance may be opened;
- no score-weight, rotation-frequency, basket, or selection-count search is allowed in v1.

## Next gate

Issue #216 may now build the real A-share provider and run the four predeclared baselines. Freezing the pool authorizes validation; it does not establish strategy effectiveness or trade readiness.
