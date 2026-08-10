import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  Check,
  ChevronRight,
  Database,
  Github,
  Layers3,
  Moon,
  Orbit,
  ShieldCheck,
  Sun,
} from 'lucide-react';
import type { GovernedRunSummary } from '@/lib/governed-run';
import type { CanonicalMetricV2 } from '@/lib/model-run-bundle-v2';
import { useGlobalStore } from '@/store/globalStore';

const FAMILY_ORDER = ['qqq_rotation', 'cn_ranker', 'byd_allocation', 'us_ranker'];

const fallbackFleetRows = [
  { name: 'QQQR v4.3', detail: 'US systematic rotation', status: 'Formal' },
  { name: 'CN x1.1', detail: 'China equity ranking', status: 'Formal' },
  { name: 'BYD v1.2', detail: 'Adaptive single-stock allocation', status: 'Formal' },
  { name: 'US x1.1', detail: 'US equity ranking', status: 'Formal' },
];

const evidenceChecks = [
  'Model identity, benchmark and evidence cutoff stay attached',
  'Performance, drawdown, holdings and trades are retained',
  'Current targets never imply brokerage execution',
  'Missing or stale operating evidence fails visibly',
];

type LandingPerformancePoint = {
  account: number;
  bench_qqq?: number;
  date: string;
};

function metric(run: GovernedRunSummary, id: string): CanonicalMetricV2 | null {
  const metrics = Array.isArray(run.summary.metrics) ? run.summary.metrics : [];
  return (metrics as CanonicalMetricV2[]).find((item) => item.metric_id === id) ?? null;
}

function metricPercent(run: GovernedRunSummary, id: string, signed = false): string {
  const item = metric(run, id);
  if (item?.availability_status !== 'available' || typeof item.value !== 'number') return '—';
  const value = item.value * 100;
  return `${signed && value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function metricDecimal(run: GovernedRunSummary, id: string): string {
  const item = metric(run, id);
  return item?.availability_status === 'available' && typeof item.value === 'number'
    ? item.value.toFixed(2)
    : '—';
}

function strategyFocus(run: GovernedRunSummary): string {
  if (run.modelFamilyId === 'qqq_rotation') return 'US systematic rotation';
  if (run.modelFamilyId === 'cn_ranker') return 'China equity ranking';
  if (run.modelFamilyId === 'byd_allocation') return 'Adaptive single-stock allocation';
  if (run.modelFamilyId === 'us_ranker') return 'US equity ranking';
  return `${run.market.toUpperCase()} systematic strategy`;
}

function selectFleetRuns(runs: GovernedRunSummary[]): GovernedRunSummary[] {
  const latestByFamily = new Map<string, GovernedRunSummary>();
  [...runs]
    .sort((a, b) => b.evidenceCutoff.localeCompare(a.evidenceCutoff))
    .forEach((run) => {
      if (!latestByFamily.has(run.modelFamilyId)) latestByFamily.set(run.modelFamilyId, run);
    });
  return FAMILY_ORDER.map((family) => latestByFamily.get(family)).filter((run): run is GovernedRunSummary => Boolean(run));
}

function ThemeButton() {
  const { theme, setTheme } = useGlobalStore();
  return (
    <button
      type="button"
      className="landing-icon-button"
      aria-label={theme === 'dark' ? 'Use light theme' : 'Use dark theme'}
      onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
    >
      {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

function WindowChrome({ title, meta }: { title: string; meta: string }) {
  return (
    <div className="landing-window-chrome">
      <div className="flex items-center gap-1.5" aria-hidden="true"><span /><span /><span /></div>
      <p>{title}</p>
      <p>{meta}</p>
    </div>
  );
}

function FleetPreview({ runs }: { runs: GovernedRunSummary[] }) {
  const selectedRuns = selectFleetRuns(runs);
  const rows = selectedRuns.length > 0
    ? selectedRuns.map((run) => ({
        name: run.title,
        detail: strategyFocus(run),
        status: metricPercent(run, 'total_return', true),
      }))
    : fallbackFleetRows;
  const evidenceCutoff = selectedRuns[0]?.evidenceCutoff;

  return (
    <div className="landing-product-window landing-runs-window">
      <WindowChrome title="Strategy fleet" meta="Formal strategy surface" />
      <div className="landing-window-body">
        <div className="landing-preview-sidebar" aria-hidden="true">
          <div className="landing-mini-brand"><Orbit className="h-4 w-4" /></div>
          <span className="is-active" /><span /><span /><span />
        </div>
        <div className="landing-runs-content">
          <div className="landing-preview-heading">
            <div><p className="landing-preview-kicker">Strategy console</p><h2>See the models before reading the machinery.</h2></div>
            <div className="landing-preview-status"><ShieldCheck className="h-3.5 w-3.5" /> Formal evidence</div>
          </div>
          <div className="landing-run-table">
            <div className="landing-run-table-head"><span>Strategy</span><span>Focus</span><span>Total return</span><span>Inspect</span></div>
            {rows.map((row, index) => (
              <div className={`landing-run-row ${index === 0 ? 'is-selected' : ''}`} key={row.name}>
                <span className="landing-run-name"><Layers3 className="h-4 w-4" />{row.name}</span>
                <span>{row.detail}</span>
                <span className="landing-run-badge landing-run-badge-blue">{row.status}</span>
                <span className="landing-evidence-link">Open <ChevronRight className="h-3.5 w-3.5" /></span>
              </div>
            ))}
          </div>
          <div className="landing-run-footer">
            <span><Database className="h-3.5 w-3.5" /> {evidenceCutoff ? `Evidence through ${evidenceCutoff}` : 'Formal catalog loading'}</span>
            <span><ShieldCheck className="h-3.5 w-3.5" /> Read-only research surface</span>
            <span><BarChart3 className="h-3.5 w-3.5" /> Performance stays public</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function isPerformancePoint(value: unknown): value is LandingPerformancePoint {
  if (!value || typeof value !== 'object') return false;
  const row = value as Record<string, unknown>;
  return typeof row.account === 'number' && typeof row.date === 'string';
}

function PerformancePreview({ run }: { run: GovernedRunSummary | null }) {
  const [performance, setPerformance] = useState<LandingPerformancePoint[]>([]);
  const [loadState, setLoadState] = useState<'idle' | 'loading' | 'ready' | 'error'>('idle');

  useEffect(() => {
    if (!run) {
      setPerformance([]);
      setLoadState('idle');
      return undefined;
    }
    let cancelled = false;
    setLoadState('loading');
    void import('@/lib/governed-run')
      .then(({ loadRunSection }) => loadRunSection(run, 'performance'))
      .then((section) => {
        if (cancelled) return;
        const report = section && typeof section === 'object' && Array.isArray((section as Record<string, unknown>).report)
          ? ((section as Record<string, unknown>).report as unknown[]).filter(isPerformancePoint)
          : [];
        setPerformance(report);
        setLoadState(report.length > 1 ? 'ready' : 'error');
      })
      .catch(() => {
        if (!cancelled) {
          setPerformance([]);
          setLoadState('error');
        }
      });
    return () => { cancelled = true; };
  }, [run]);

  const trace = useMemo(() => {
    if (performance.length < 2) return null;
    const stride = Math.max(1, Math.ceil(performance.length / 96));
    const sampled = performance.filter((_, index) => index % stride === 0 || index === performance.length - 1);
    const values = sampled.flatMap((point) => [point.account, point.bench_qqq ?? 1]).filter(Number.isFinite);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const spread = max - min || 1;
    const width = 1000;
    const height = 300;
    const pad = 24;
    const makePoints = (pick: (point: LandingPerformancePoint) => number) => sampled.map((point, index) => {
      const x = pad + (index / Math.max(1, sampled.length - 1)) * (width - pad * 2);
      const y = height - pad - ((pick(point) - min) / spread) * (height - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return {
      strategy: makePoints((point) => point.account),
      benchmark: makePoints((point) => point.bench_qqq ?? 1),
      start: sampled[0].date,
      end: sampled[sampled.length - 1].date,
    };
  }, [performance]);

  const stats = run ? [
    ['Total return', metricPercent(run, 'total_return', true)],
    ['CAGR', metricPercent(run, 'annualized_return', true)],
    ['Sharpe', metricDecimal(run, 'sharpe_ratio')],
    ['Max drawdown', metricPercent(run, 'max_drawdown')],
  ] : [
    ['Total return', '—'],
    ['CAGR', '—'],
    ['Sharpe', '—'],
    ['Max drawdown', '—'],
  ];

  return (
    <div className="landing-product-window landing-evidence-window">
      <WindowChrome title="Formal performance" meta={run ? `Evidence through ${run.evidenceCutoff}` : 'Retained trace'} />
      <div className="landing-backtest-body">
        <div className="landing-backtest-header">
          <div>
            <p className="landing-preview-kicker">Performance & risk</p>
            <h3>{run ? `${run.title} against ${run.benchmark.toUpperCase()}` : 'Formal strategy against its declared benchmark.'}</h3>
          </div>
          <div className="landing-chart-legend" aria-label="Performance chart legend">
            <span className="strategy" /> Strategy
            <span className="benchmark" /> Benchmark
          </div>
        </div>
        <div className="landing-chart-area" role="img" aria-label={run ? `${run.title} formal performance trace` : 'Formal performance trace loading'}>
          <div className="landing-chart-grid" aria-hidden="true" />
          {trace ? (
            <svg viewBox="0 0 1000 300" preserveAspectRatio="none" aria-hidden="true">
              <polyline points={trace.benchmark} className="landing-chart-benchmark" />
              <polyline points={trace.strategy} className="landing-chart-strategy" />
            </svg>
          ) : (
            <div className="absolute inset-0 flex items-center justify-center text-xs font-semibold text-muted-foreground">
              {loadState === 'error' ? 'Formal trace unavailable' : 'Loading retained formal trace'}
            </div>
          )}
          {trace && <p className="absolute bottom-3 left-4 text-[9px] font-semibold text-muted-foreground">{trace.start} → {trace.end}</p>}
        </div>
        <div className="landing-backtest-rail">
          {stats.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}
        </div>
      </div>
    </div>
  );
}

function EvidencePreview() {
  return (
    <div className="landing-product-window landing-evidence-window">
      <WindowChrome title="Strategy evidence" meta="Decision to provenance" />
      <div className="landing-evidence-body">
        <div className="landing-evidence-map">
          <div className="landing-evidence-node"><Layers3 className="h-4 w-4" /><span>Now</span><small>State</small></div>
          <ChevronRight className="landing-evidence-arrow" />
          <div className="landing-evidence-node"><BarChart3 className="h-4 w-4" /><span>Performance</span><small>Risk</small></div>
          <ChevronRight className="landing-evidence-arrow" />
          <div className="landing-evidence-node"><Database className="h-4 w-4" /><span>Drivers</span><small>Lineage</small></div>
          <ChevronRight className="landing-evidence-arrow" />
          <div className="landing-evidence-node is-final"><ShieldCheck className="h-4 w-4" /><span>Trust</span><small>Bounded</small></div>
        </div>
        <div className="landing-decision-panel">
          <div>
            <p className="landing-preview-kicker">One strategy, one evidence path</p>
            <h3>Move from the decision to the proof behind it.</h3>
            <p>Alpha Engine keeps operating state and formal research in one reading path instead of making users navigate the repository's subsystem structure.</p>
          </div>
          <div className="landing-check-list">
            {evidenceChecks.map((item) => <div key={item}><Check className="h-4 w-4" /><span>{item}</span></div>)}
          </div>
        </div>
      </div>
    </div>
  );
}

export function LandingPage() {
  const theme = useGlobalStore((state) => state.theme);
  const [formalRuns, setFormalRuns] = useState<GovernedRunSummary[]>([]);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.title = 'Alpha Engine — Systematic Strategy Research & Monitoring';
    const description = document.querySelector('meta[name="description"]');
    description?.setAttribute('content', 'Inspect systematic strategies, formal performance, risk, current decision state and the governed evidence behind each model.');
  }, [theme]);

  useEffect(() => {
    let cancelled = false;
    void import('@/lib/governed-run')
      .then(({ loadFormalRuns }) => loadFormalRuns())
      .then((result) => {
        if (!cancelled) setFormalRuns(result.runs);
      })
      .catch(() => {
        if (!cancelled) setFormalRuns([]);
      });
    return () => { cancelled = true; };
  }, []);

  const featuredRun = selectFleetRuns(formalRuns).find((run) => run.modelFamilyId === 'qqq_rotation') ?? selectFleetRuns(formalRuns)[0] ?? null;

  return (
    <div className="alpha-landing">
      <header className="landing-nav">
        <Link to="/" className="landing-brand" aria-label="Alpha Engine home">
          <span className="landing-brand-mark"><Orbit className="h-4 w-4" /></span>
          <span><strong>Alpha Engine</strong><small>Systematic strategies</small></span>
        </Link>
        <nav aria-label="Product navigation">
          <a href="#strategies">Strategies</a>
          <a href="#performance">Performance</a>
          <a href="#evidence">Evidence</a>
          <a href="https://github.com/liuh886/alpha_engine" target="_blank" rel="noreferrer"><Github className="h-4 w-4" /><span className="sr-only">GitHub</span></a>
          <ThemeButton />
          <Link className="landing-nav-cta" to="/app">Open console <ArrowRight className="h-3.5 w-3.5" /></Link>
        </nav>
      </header>

      <main>
        <section className="landing-hero" id="strategies">
          <div className="landing-hero-copy">
            <h1>Know what your systematic strategy is doing — and why.</h1>
            <p>Alpha Engine brings current state, target allocation, next decision, formal performance, risk and research evidence into one medium-frequency strategy console.</p>
            <div className="landing-actions">
              <Link className="landing-primary-action" to="/strategies">Explore strategies <ArrowRight className="h-4 w-4" /></Link>
              <Link className="landing-secondary-action" to="/app">Open console</Link>
            </div>
            <p className="landing-trust-line">Read-only · Evidence-governed · No broker execution</p>
          </div>
          <FleetPreview runs={formalRuns} />
        </section>

        <section className="landing-story-section" id="performance">
          <div className="landing-section-copy">
            <span>01</span>
            <h2>Performance before persuasion.</h2>
            <p>Each formal strategy exposes retained return and risk evidence against its declared benchmark. Start with the result, then decide how much operational detail you need.</p>
            <Link to="/strategies">Inspect formal performance <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <PerformancePreview run={featuredRun} />
        </section>

        <section className="landing-story-section landing-story-reverse" id="evidence">
          <div className="landing-section-copy">
            <span>02</span>
            <h2>Every decision is traceable.</h2>
            <p>Model identity, benchmark, evidence cutoff, performance, drivers and retained research artifacts stay connected without turning the operating screen into an infrastructure dashboard.</p>
            <Link to="/research">Open research evidence <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <EvidencePreview />
        </section>

        <section className="landing-final-cta">
          <div><h2>See the model. Then inspect the decision.</h2><p>Start with the formal strategy fleet and drill into operating detail only when the decision requires it.</p></div>
          <Link className="landing-primary-action" to="/strategies">Explore Alpha Engine <ArrowRight className="h-4 w-4" /></Link>
        </section>
      </main>

      <footer className="landing-footer"><p>Alpha Engine</p><p>Governed medium-frequency strategy research and monitoring</p></footer>
    </div>
  );
}
