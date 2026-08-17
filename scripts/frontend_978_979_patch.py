from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'missing patch anchor: {path}: {old[:80]!r}')
    file.write_text(text.replace(old, new, 1), encoding='utf-8')


# Shared critical-path assets: current canonical shell/referral only, non-blocking CSS.
replace_once(
    'qlib-dashboard/index.html',
    '''  <link rel="stylesheet" href="https://liuh886.github.io/admin/shared/account-shell.css?v=6" />\n  <link rel="stylesheet" href="https://liuh886.github.io/admin/shared/product-referral.css?v=3" />\n  <link rel="stylesheet" href="./account-integration.css" />''',
    '''  <link rel="preconnect" href="https://liuh886.github.io" crossorigin />\n  <link rel="preload" href="https://liuh886.github.io/admin/shared/account-shell.css?v=6" as="style" onload="this.onload=null;this.rel='stylesheet'" />\n  <link rel="preload" href="https://liuh886.github.io/admin/shared/product-referral.css?v=3" as="style" onload="this.onload=null;this.rel='stylesheet'" />\n  <noscript>\n    <link rel="stylesheet" href="https://liuh886.github.io/admin/shared/account-shell.css?v=6" />\n    <link rel="stylesheet" href="https://liuh886.github.io/admin/shared/product-referral.css?v=3" />\n  </noscript>\n  <link rel="stylesheet" href="./account-integration.css" />''',
)

# Account/referral consumer contract is the alignment check; do not add a second manifest/config authority.
replace_once(
    'qlib-dashboard/scripts/check-account.mjs',
    '''for (const reference of [\n  'https://liuh886.github.io/admin/shared/account-shell.css?v=6',\n  'https://liuh886.github.io/admin/shared/account-shell.js?v=7',\n  './account-integration.css',\n]) {\n  if (!html.includes(reference)) throw new Error(`index.html missing canonical account asset: ${reference}`);\n}\nif (html.includes('./account-shell/')) throw new Error('AlphaEngine must not ship a duplicated account-shell copy.');''',
    '''for (const reference of [\n  'https://liuh886.github.io/admin/shared/account-shell.css?v=6',\n  'https://liuh886.github.io/admin/shared/account-shell.js?v=7',\n  'https://liuh886.github.io/admin/shared/product-referral.css?v=3',\n  'https://liuh886.github.io/admin/shared/product-referral.js?v=5',\n  './account-integration.css',\n]) {\n  if (!html.includes(reference)) throw new Error(`index.html missing canonical shared asset: ${reference}`);\n}\nif (!html.includes('<link rel="preconnect" href="https://liuh886.github.io" crossorigin')) {\n  throw new Error('Shared asset origin must be preconnected before first paint.');\n}\nconst scriptEnabledHtml = html.replace(/<noscript>[\\s\\S]*?<\\/noscript>/g, '');\nfor (const stylesheet of [\n  'https://liuh886.github.io/admin/shared/account-shell.css?v=6',\n  'https://liuh886.github.io/admin/shared/product-referral.css?v=3',\n]) {\n  if (!scriptEnabledHtml.includes(`<link rel="preload" href="${stylesheet}" as="style"`)) {\n    throw new Error(`Shared stylesheet must use preload-onload: ${stylesheet}`);\n  }\n}\nif (/<link\\s+rel=["']stylesheet["'][^>]+liuh886\\.github\\.io\\/admin\\/shared\\//i.test(scriptEnabledHtml)) {\n  throw new Error('Script-enabled first paint must not synchronously block on shared cross-origin styles.');\n}\nif (!html.includes('<script async src="https://liuh886.github.io/admin/shared/account-shell.js?v=7"')) {\n  throw new Error('Canonical account shell must remain non-blocking.');\n}\nif (!html.includes('<script defer src="https://liuh886.github.io/admin/shared/product-referral.js?v=5"')) {\n  throw new Error('Canonical referral runtime must remain deferred.');\n}\nif (html.includes('./account-shell/')) throw new Error('AlphaEngine must not ship a duplicated account-shell copy.');''',
)

# PerformanceCharts delegates async lifecycle to one hook and uses theme tokens.
replace_once(
    'qlib-dashboard/src/components/PerformanceCharts.tsx',
    '''import {\n  loadMarketEvidenceCatalog,\n  loadSecurityMarketEvidence,\n  type MarketBar,\n  type MarketEvidenceCatalog,\n  type MarketEvidenceMarket,\n} from '@/lib/market-evidence';''',
    '''import type { MarketEvidenceMarket } from '@/lib/market-evidence';\nimport { useMarketComparisons } from '@/hooks/useMarketComparisons';''',
)
replace_once(
    'qlib-dashboard/src/components/PerformanceCharts.tsx',
    "const COMPARISON_STROKES = ['#06b6d4', '#8b5cf6', '#22c55e', '#ef4444', '#64748b', '#ec4899'];",
    "const COMPARISON_STROKES = ['hsl(var(--chart-2))', 'hsl(var(--chart-4))', 'hsl(var(--chart-3))', 'hsl(var(--chart-5))', 'hsl(var(--chart-1))'];",
)
replace_once(
    'qlib-dashboard/src/components/PerformanceCharts.tsx',
    '''  const [rangeKey, setRangeKey] = useState<RangeKey>('all');\n  const [marketCatalogs, setMarketCatalogs] = useState<MarketEvidenceCatalog[]>([]);\n  const [marketBars, setMarketBars] = useState<Record<string, MarketBar[]>>({});\n  const [loadingComparisonKeys, setLoadingComparisonKeys] = useState<string[]>([]);\n\n  useEffect(() => {\n    let cancelled = false;\n    setMarketCatalogs([]);\n    setMarketBars({});\n    setSelectedComparisonKeys(null);\n    if (!market) return () => { cancelled = true; };\n\n    const markets: MarketEvidenceMarket[] = market === 'us' ? ['us', 'cn'] : ['cn', 'us'];\n    Promise.allSettled(markets.map(loadMarketEvidenceCatalog)).then(results => {\n      if (cancelled) return;\n      setMarketCatalogs(results.flatMap(result => result.status === 'fulfilled' ? [result.value] : []));\n    });\n    return () => { cancelled = true; };\n  }, [market]);''',
    '''  const [rangeKey, setRangeKey] = useState<RangeKey>('all');\n  const {\n    catalogs: marketCatalogs,\n    marketBars,\n    loadingKeys: loadingComparisonKeys,\n    failedKeys: failedComparisonKeys,\n    catalogsLoading,\n    ensureCatalogs,\n    requestComparison,\n  } = useMarketComparisons(market);\n\n  useEffect(() => {\n    setSelectedComparisonKeys(null);\n  }, [market]);''',
)
replace_once(
    'qlib-dashboard/src/components/PerformanceCharts.tsx',
    '''  const requestMarketComparison = (key: string) => {\n    if (marketBars[key] || loadingComparisonKeys.includes(key)) return;\n    const option = comparisonOptions.find(candidate => candidate.key === key);\n    const symbol = option?.marketSymbol?.symbol;\n    const catalog = option?.market\n      ? marketCatalogs.find(candidate => candidate.market === option.market) ?? null\n      : null;\n    if (!catalog || !symbol) return;\n    setLoadingComparisonKeys(current => current.includes(key) ? current : [...current, key]);\n    loadSecurityMarketEvidence(catalog, symbol)\n      .then(evidence => {\n        setMarketBars(current => ({ ...current, [key]: evidence.bars }));\n      })\n      .catch(() => undefined)\n      .finally(() => {\n        setLoadingComparisonKeys(current => current.filter(candidate => candidate !== key));\n      });\n  };''',
    '''  const requestMarketComparison = (key: string) => {\n    const option = comparisonOptions.find(candidate => candidate.key === key);\n    void requestComparison({\n      key,\n      market: option?.market,\n      symbol: option?.marketSymbol?.symbol,\n    });\n  };''',
)
replace_once(
    'qlib-dashboard/src/components/PerformanceCharts.tsx',
    '''                loadingKeys={loadingComparisonKeys}\n                unavailableLabel={declaredBenchmark ? `${declaredBenchmark.label} unavailable` : undefined}\n                onPrimaryChange={handlePrimaryBenchmarkChange}\n                onToggle={handleComparisonToggle}\n              />''',
    '''                loadingKeys={loadingComparisonKeys}\n                failedKeys={failedComparisonKeys}\n                catalogsLoading={catalogsLoading}\n                unavailableLabel={declaredBenchmark ? `${declaredBenchmark.label} unavailable` : undefined}\n                onOpenChange={(open) => { if (open) void ensureCatalogs(); }}\n                onPrimaryChange={handlePrimaryBenchmarkChange}\n                onToggle={handleComparisonToggle}\n                onRetry={requestMarketComparison}\n              />''',
)
replace_once(
    'qlib-dashboard/src/components/PerformanceCharts.tsx',
    "stroke={isPrimary ? '#f59e0b' : COMPARISON_STROKES[index % COMPARISON_STROKES.length]}",
    "stroke={isPrimary ? 'hsl(var(--chart-3))' : COMPARISON_STROKES[index % COMPARISON_STROKES.length]}",
)

# Comparison control owns visible loading/error/retry states.
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '''  loadingKeys = [],\n  unavailableLabel,\n  onPrimaryChange,\n  onToggle,''',
    '''  loadingKeys = [],\n  failedKeys = [],\n  catalogsLoading = false,\n  unavailableLabel,\n  onOpenChange,\n  onPrimaryChange,\n  onToggle,\n  onRetry,''',
)
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '''  loadingKeys?: string[];\n  unavailableLabel?: string;\n  onPrimaryChange: (key: string) => void;\n  onToggle: (key: string) => void;''',
    '''  loadingKeys?: string[];\n  failedKeys?: string[];\n  catalogsLoading?: boolean;\n  unavailableLabel?: string;\n  onOpenChange?: (open: boolean) => void;\n  onPrimaryChange: (key: string) => void;\n  onToggle: (key: string) => void;\n  onRetry: (key: string) => void;''',
)
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '''  const selected = new Set(selectedKeys);\n  const loading = new Set(loadingKeys);''',
    '''  const selected = new Set(selectedKeys);\n  const loading = new Set(loadingKeys);\n  const failed = new Set(failedKeys);''',
)
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '<Popover.Root>',
    '<Popover.Root onOpenChange={onOpenChange}>',
)
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '''            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">\n              Star sets the primary benchmark for Excess. Check any number of series to overlay.\n            </p>\n          </div>''',
    '''            <p className="mt-0.5 text-[10px] leading-relaxed text-muted-foreground">\n              Star sets the primary benchmark for Excess. Check any number of series to overlay.\n            </p>\n            {catalogsLoading && <p className="mt-1 text-[10px] text-muted-foreground">Loading stock pools…</p>}\n          </div>''',
)
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '''                      const isSelected = selected.has(option.key);\n                      const isLoading = loading.has(option.key);''',
    '''                      const isSelected = selected.has(option.key);\n                      const isLoading = loading.has(option.key);\n                      const isFailed = failed.has(option.key);''',
)
replace_once(
    'qlib-dashboard/src/components/ChartBenchmarkControl.tsx',
    '''                            {isLoading && <span className="text-[9px] text-muted-foreground">Loading</span>}\n                          </button>\n                          <button\n                            type="button"\n                            aria-label={`Use ${option.label} as primary benchmark`}''',
    '''                            {isLoading && <span className="text-[9px] text-muted-foreground">Loading</span>}\n                            {isFailed && <span className="text-[9px] text-destructive">Load failed</span>}\n                          </button>\n                          {isFailed && (\n                            <button\n                              type="button"\n                              aria-label={`Retry ${option.label}`}\n                              onClick={() => onRetry(option.key)}\n                              className="rounded px-1.5 py-1 text-[9px] font-semibold text-destructive hover:bg-destructive/10"\n                            >\n                              Retry\n                            </button>\n                          )}\n                          <button\n                            type="button"\n                            aria-label={`Use ${option.label} as primary benchmark`}''',
)

# Share/clipboard: deterministic visible fallback; standard popover layer.
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    "type ShareState = 'idle' | 'copied';",
    "type ShareState = 'idle' | 'copied' | 'failed';",
)
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    "export async function shareUrl({ title, text, url }: { title: string; text: string; url: string }): Promise<'shared' | 'copied' | 'cancelled'> {",
    "export async function shareUrl({ title, text, url }: { title: string; text: string; url: string }): Promise<'shared' | 'copied' | 'cancelled' | 'failed'> {",
)
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    '''  await navigator.clipboard.writeText(url);\n  return 'copied';''',
    '''  try {\n    await navigator.clipboard.writeText(url);\n    return 'copied';\n  } catch {\n    return 'failed';\n  }''',
)
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    '''  const [state, setState] = useState<ShareState>('idle');\n  const [open, setOpen] = useState(false);''',
    '''  const [state, setState] = useState<ShareState>('idle');\n  const [open, setOpen] = useState(false);\n  const [fallbackUrl, setFallbackUrl] = useState('');''',
)
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    '''  const handleShare = async () => {\n    const result = await shareUrl({\n      title: 'Alpha Engine — Systematic Strategy Console',\n      text: 'Inspect systematic strategies, current decisions, formal performance, risk and evidence in Alpha Engine.',\n      url: window.location.href,\n    });\n    if (result === 'copied') setState('copied');\n    if (result !== 'cancelled') setOpen(false);\n  };''',
    '''  const handleShare = async () => {\n    const url = window.location.href;\n    const result = await shareUrl({\n      title: 'Alpha Engine — Systematic Strategy Console',\n      text: 'Inspect systematic strategies, current decisions, formal performance, risk and evidence in Alpha Engine.',\n      url,\n    });\n    if (result === 'failed') {\n      setFallbackUrl(url);\n      setState('failed');\n      return;\n    }\n    if (result === 'copied') setState('copied');\n    if (result !== 'cancelled') setOpen(false);\n  };''',
)
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    'className="z-[2147482500] w-[min(19rem,calc(100vw-24px))]',
    'className="z-50 w-[min(19rem,calc(100vw-24px))]',
)
replace_once(
    'qlib-dashboard/src/components/ProductShareButton.tsx',
    '''          </button>\n\n          <div className="my-1 h-px bg-border/70" />''',
    '''          </button>\n\n          {state === 'failed' && (\n            <div role="status" className="mx-1 mb-1 rounded-lg border border-destructive/30 bg-destructive/5 p-2.5">\n              <p className="text-xs font-medium text-destructive">Automatic copy failed. Select the link below and copy it manually.</p>\n              <input\n                aria-label="Share link for manual copy"\n                readOnly\n                value={fallbackUrl}\n                onFocus={(event) => event.currentTarget.select()}\n                className="mt-2 h-8 w-full rounded-md border bg-background px-2 font-mono text-[10px] text-foreground"\n              />\n            </div>\n          )}\n\n          <div className="my-1 h-px bg-border/70" />''',
)

# iPadOS desktop-class UA still needs iOS manual install guidance.
replace_once(
    'qlib-dashboard/src/components/PwaInstall.tsx',
    '''function isIosDevice(): boolean {\n  return /iphone|ipad|ipod/i.test(navigator.userAgent);\n}''',
    '''function isIosDevice(): boolean {\n  return /iphone|ipad|ipod/i.test(navigator.userAgent)\n    || (/macintosh/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1);\n}''',
)

# Landing fallback names are timeless family labels; actual versions always come from the formal catalog.
replace_once(
    'qlib-dashboard/src/pages/LandingPage.tsx',
    '''const fallbackFleetRows = [\n  { name: 'QQQR v4.3', detail: 'US systematic rotation', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n  { name: 'CN x1.1', detail: 'China equity ranking', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n  { name: 'BYD v1.3', detail: 'Adaptive single-stock allocation', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n  { name: 'US x1.3', detail: 'Active US research baseline', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n];''',
    '''const fallbackFleetRows = [\n  { name: 'QQQ rotation', detail: 'US systematic rotation', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n  { name: 'China ranker', detail: 'China equity ranking', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n  { name: 'BYD allocation', detail: 'Adaptive single-stock allocation', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n  { name: 'US ranker', detail: 'Active US research baseline', totalReturn: '—', cagr: '—', maxDrawdown: '—' },\n];''',
)
replace_once(
    'qlib-dashboard/src/pages/LandingPage.tsx',
    '''  const evidenceCutoff = selectedRuns[0]?.evidenceCutoff;\n\n  return (\n    <div className="landing-product-window landing-runs-window">''',
    '''  const evidenceCutoff = selectedRuns[0]?.evidenceCutoff;\n  const usingFallback = selectedRuns.length === 0;\n\n  return (\n    <div className="landing-product-window landing-runs-window" data-fallback={usingFallback ? 'true' : undefined}>''',
)

# Product boundary: public formal evidence is intentional; Pro protects current operations via RLS.
(ROOT / 'docs/architecture/frontend_access_control.md').write_text('''# Alpha Engine frontend access control\n\n## Product contract\n\nAlpha Engine has four monotonic product levels: `public`, `authenticated`, `pro`, and `owner`. Owner inherits Pro; Pro inherits authenticated and public access. Account tier is never inferred from a model family.\n\nThe product has two deliberately different publication boundaries:\n\n- **Formal historical research evidence is public.** Retained backtests, benchmarks, performance and risk evidence published under the GitHub Pages formal catalog are designed to be inspectable without payment. The product must not describe those static artifacts as confidential or Pro-exclusive.\n- **Current strategy operations are the paid boundary.** Current holdings, target allocations, current signals and next-decision state are read from Supabase-backed strategy operation resources. Their minimum tier is resolved from `product_access_policies`, and access to protected rows is enforced at the Supabase/RLS boundary, including the `alpha_engine.pro` entitlement. React gates mirror that policy for navigation and presentation; they are not the security authority.\n\nThis is the canonical product positioning: **public evidence earns trust; Pro unlocks current operational decision surfaces.**\n\n## Policy resources\n\n`product_access_policies` stores minimum tiers for two resource types:\n\n- `strategy` — keyed by stable `strategy_id` for current operation snapshots;\n- `module` — keyed by a declared frontend module resource ID.\n\nOwner changes policy rows from `/settings/access`. Browser defaults are fail-safe only while Supabase policy state is loading or unavailable; they do not create a second writable policy authority.\n\n## Supabase boundary\n\nPolicy writes require an authenticated JWT whose server-controlled `app_metadata.alpha_engine_role` is `owner`. Strategy operation reads are split by tier in RLS: public/authenticated rows can be selected at their declared tier, while Pro/Owner rows require the corresponding entitlement/role. Never place service-role credentials in browser assets or this repository.\n\n## Static deployment boundary\n\nGitHub Pages serves the formal historical catalog as public static files by design. UI gating of those static URLs is a reading affordance, not confidentiality. If a future product decision makes a historical artifact genuinely private, that artifact must leave GitHub Pages and move behind an authenticated transport/RLS boundary before the product claims exclusivity. Until such a decision exists, no duplicate private copy or migration path should be maintained.\n''', encoding='utf-8')

# Repository hygiene.
gitignore = ROOT / '.gitignore'
text = gitignore.read_text(encoding='utf-8')
if 'ruff_errors.txt' not in text:
    text = text.replace('coverage.xml\n', 'coverage.xml\nruff_errors.txt\n', 1)
gitignore.write_text(text, encoding='utf-8')

replace_once(
    '.pre-commit-config.yaml',
    '''repos:\n  - repo: https://github.com/astral-sh/ruff-pre-commit''',
    '''repos:\n  - repo: https://github.com/pre-commit/pre-commit-hooks\n    rev: v5.0.0\n    hooks:\n      - id: end-of-file-fixer\n  - repo: https://github.com/astral-sh/ruff-pre-commit''',
)

ruff = ROOT / 'ruff_errors.txt'
if ruff.exists():
    ruff.unlink()
