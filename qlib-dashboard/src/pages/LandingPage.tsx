import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  BarChart3,
  Check,
  ChevronRight,
  Database,
  FileCheck2,
  GitCompareArrows,
  Github,
  Layers3,
  Moon,
  Orbit,
  ShieldCheck,
  Sun,
} from 'lucide-react';
import { useGlobalStore } from '@/store/globalStore';

const modelRuns = [
  { name: 'US x1.1', market: 'US 87', status: 'Formal', tone: 'blue' },
  { name: 'CN x1.1', market: 'CN 130', status: 'Candidate', tone: 'amber' },
  { name: 'QQQ Rotation v4.2', market: 'ETF', status: 'Formal', tone: 'blue' },
  { name: 'BYD v1.1', market: 'Single asset', status: 'Formal', tone: 'blue' },
];

const evidenceChecks = [
  'Point-in-time data boundary declared',
  'Benchmark and transaction rules attached',
  'Holdings, signals, and rebalance log preserved',
  'Notebook and decision record linked',
];

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
      <div className="flex items-center gap-1.5" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <p>{title}</p>
      <p>{meta}</p>
    </div>
  );
}

function RunsPreview() {
  return (
    <div className="landing-product-window landing-runs-window">
      <WindowChrome title="Governed model runs" meta="Artifact studio" />
      <div className="landing-window-body">
        <div className="landing-preview-sidebar" aria-hidden="true">
          <div className="landing-mini-brand"><Orbit className="h-4 w-4" /></div>
          <span className="is-active" />
          <span />
          <span />
          <span />
        </div>
        <div className="landing-runs-content">
          <div className="landing-preview-heading">
            <div>
              <p className="landing-preview-kicker">Research workspace</p>
              <h2>Choose the run before reading the result.</h2>
            </div>
            <div className="landing-preview-status"><ShieldCheck className="h-3.5 w-3.5" /> Evidence governed</div>
          </div>
          <div className="landing-run-table">
            <div className="landing-run-table-head">
              <span>Model run</span><span>Universe</span><span>Status</span><span>Evidence</span>
            </div>
            {modelRuns.map((run, index) => (
              <div className={`landing-run-row ${index === 0 ? 'is-selected' : ''}`} key={run.name}>
                <span className="landing-run-name"><Layers3 className="h-4 w-4" />{run.name}</span>
                <span>{run.market}</span>
                <span className={`landing-run-badge landing-run-badge-${run.tone}`}>{run.status}</span>
                <span className="landing-evidence-link">Open <ChevronRight className="h-3.5 w-3.5" /></span>
              </div>
            ))}
          </div>
          <div className="landing-run-footer">
            <span><Database className="h-3.5 w-3.5" /> Data cutoff declared</span>
            <span><FileCheck2 className="h-3.5 w-3.5" /> Immutable artifact</span>
            <span><GitCompareArrows className="h-3.5 w-3.5" /> Compatible comparison</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function BacktestPreview() {
  return (
    <div className="landing-product-window landing-backtest-window">
      <WindowChrome title="Formal backtest" meta="Strategy vs benchmark" />
      <div className="landing-backtest-body">
        <div className="landing-backtest-header">
          <div>
            <p className="landing-preview-kicker">US x1.1 / formal run</p>
            <h3>Performance is only useful when its source is visible.</h3>
          </div>
          <div className="landing-chart-legend"><span className="strategy" /> Strategy <span className="benchmark" /> Benchmark</div>
        </div>
        <div className="landing-chart-area">
          <div className="landing-chart-grid" aria-hidden="true" />
          <svg viewBox="0 0 900 300" role="img" aria-label="Illustrative strategy and benchmark equity curves">
            <path className="landing-chart-benchmark" d="M12 255 C82 249 112 232 168 238 S260 210 320 218 S420 184 482 190 S575 151 640 158 S742 120 888 108" />
            <path className="landing-chart-strategy" d="M12 255 C74 248 116 224 168 231 S252 190 318 205 S405 158 476 168 S566 115 626 129 S718 84 784 91 S850 48 888 56" />
            <circle cx="888" cy="56" r="5" className="landing-chart-point" />
          </svg>
        </div>
        <div className="landing-backtest-rail">
          <div><span>Return path</span><strong>Full period</strong></div>
          <div><span>Holdings</span><strong>Every rebalance</strong></div>
          <div><span>Risk</span><strong>Drawdown visible</strong></div>
          <div><span>Attribution</span><strong>Benchmark-relative</strong></div>
        </div>
      </div>
    </div>
  );
}

function EvidencePreview() {
  return (
    <div className="landing-product-window landing-evidence-window">
      <WindowChrome title="Decision review" meta="Evidence chain" />
      <div className="landing-evidence-body">
        <div className="landing-evidence-map">
          <div className="landing-evidence-node"><Database className="h-4 w-4" /><span>Data</span><small>Lineage</small></div>
          <ChevronRight className="landing-evidence-arrow" />
          <div className="landing-evidence-node"><BarChart3 className="h-4 w-4" /><span>Factors</span><small>Diagnostics</small></div>
          <ChevronRight className="landing-evidence-arrow" />
          <div className="landing-evidence-node"><GitCompareArrows className="h-4 w-4" /><span>Backtest</span><small>Comparison</small></div>
          <ChevronRight className="landing-evidence-arrow" />
          <div className="landing-evidence-node is-final"><ShieldCheck className="h-4 w-4" /><span>Decision</span><small>Recorded</small></div>
        </div>
        <div className="landing-decision-panel">
          <div>
            <p className="landing-preview-kicker">Review contract</p>
            <h3>Every conclusion keeps its evidence attached.</h3>
            <p>Move from a promising chart to a governed decision without losing assumptions, boundaries, or the path back to source artifacts.</p>
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

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.title = 'Alpha Engine — Governed Systematic Research';
    const description = document.querySelector('meta[name="description"]');
    description?.setAttribute('content', 'Inspect governed model runs, reproduce formal backtests, trace evidence, and turn systematic research into reviewable decisions.');
  }, [theme]);

  return (
    <div className="alpha-landing">
      <header className="landing-nav">
        <Link to="/" className="landing-brand" aria-label="Alpha Engine home">
          <span className="landing-brand-mark"><Orbit className="h-4 w-4" /></span>
          <span><strong>Alpha Engine</strong><small>Governed research</small></span>
        </Link>
        <nav aria-label="Product navigation">
          <a href="#workflow">Workflow</a>
          <a href="#evidence">Evidence</a>
          <a href="https://github.com/liuh886/alpha_engine" target="_blank" rel="noreferrer"><Github className="h-4 w-4" /><span className="sr-only">GitHub</span></a>
          <ThemeButton />
          <Link className="landing-nav-cta" to="/app">Open studio <ArrowRight className="h-3.5 w-3.5" /></Link>
        </nav>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-copy">
            <h1>Turn systematic research into decisions you can inspect.</h1>
            <p>Alpha Engine connects governed model runs, reproducible backtests, and evidence trails in one local-first research studio.</p>
            <div className="landing-actions">
              <Link className="landing-primary-action" to="/app">Open Research Studio <ArrowRight className="h-4 w-4" /></Link>
              <Link className="landing-secondary-action" to="/backtests">View formal backtests</Link>
            </div>
            <p className="landing-trust-line">Local-first · Artifact-driven · Reproducible</p>
          </div>
          <RunsPreview />
        </section>

        <section className="landing-story-section" id="workflow">
          <div className="landing-section-copy">
            <span>01</span>
            <h2>See where performance came from.</h2>
            <p>A formal backtest is more than an equity curve. Alpha Engine keeps the benchmark, drawdown, holdings, signals, and rebalance history in the same review surface.</p>
            <Link to="/backtests">Explore formal backtests <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <BacktestPreview />
        </section>

        <section className="landing-story-section landing-story-reverse" id="evidence">
          <div className="landing-section-copy">
            <span>02</span>
            <h2>Keep evidence attached to every decision.</h2>
            <p>Trace a result from source data through factor evidence and model assumptions, then record what the evidence supports—and what it does not.</p>
            <Link to="/decisions">Open decision review <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <EvidencePreview />
        </section>

        <section className="landing-final-cta">
          <div>
            <h2>Research should remain reviewable after the result looks good.</h2>
            <p>Open the governed workspace and inspect the current formal model runs.</p>
          </div>
          <Link className="landing-primary-action" to="/app">Enter Alpha Engine <ArrowRight className="h-4 w-4" /></Link>
        </section>
      </main>

      <footer className="landing-footer">
        <p>Alpha Engine</p>
        <p>Governed systematic research · Local-first artifacts</p>
      </footer>
    </div>
  );
}
