import { useEffect } from 'react';
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
import { useGlobalStore } from '@/store/globalStore';

const fleetRows = [
  { name: 'Current state', detail: 'What the strategy holds now', status: 'Visible', tone: 'blue' },
  { name: 'Target allocation', detail: 'What changes at the next decision', status: 'Governed', tone: 'blue' },
  { name: 'Decision cadence', detail: 'When the strategy evaluates again', status: 'Explicit', tone: 'blue' },
  { name: 'Risk & freshness', detail: 'Whether the evidence can be trusted now', status: 'Attached', tone: 'blue' },
];

const evidenceChecks = [
  'Formal model identity and benchmark stay attached',
  'Performance, drawdown, holdings and trades are retained',
  'Current targets never imply brokerage execution',
  'Missing or stale operating evidence fails visibly',
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
      <div className="flex items-center gap-1.5" aria-hidden="true"><span /><span /><span /></div>
      <p>{title}</p>
      <p>{meta}</p>
    </div>
  );
}

function FleetPreview() {
  return (
    <div className="landing-product-window landing-runs-window">
      <WindowChrome title="Strategy fleet" meta="Decision surface" />
      <div className="landing-window-body">
        <div className="landing-preview-sidebar" aria-hidden="true">
          <div className="landing-mini-brand"><Orbit className="h-4 w-4" /></div>
          <span className="is-active" /><span /><span /><span />
        </div>
        <div className="landing-runs-content">
          <div className="landing-preview-heading">
            <div><p className="landing-preview-kicker">Operating console</p><h2>Start with what the strategies are doing now.</h2></div>
            <div className="landing-preview-status"><ShieldCheck className="h-3.5 w-3.5" /> Evidence attached</div>
          </div>
          <div className="landing-run-table">
            <div className="landing-run-table-head"><span>Decision</span><span>Meaning</span><span>Status</span><span>Inspect</span></div>
            {fleetRows.map((row, index) => (
              <div className={`landing-run-row ${index === 0 ? 'is-selected' : ''}`} key={row.name}>
                <span className="landing-run-name"><Layers3 className="h-4 w-4" />{row.name}</span>
                <span>{row.detail}</span>
                <span className={`landing-run-badge landing-run-badge-${row.tone}`}>{row.status}</span>
                <span className="landing-evidence-link">Open <ChevronRight className="h-3.5 w-3.5" /></span>
              </div>
            ))}
          </div>
          <div className="landing-run-footer">
            <span><Database className="h-3.5 w-3.5" /> Data cutoff declared</span>
            <span><ShieldCheck className="h-3.5 w-3.5" /> Fail-closed status</span>
            <span><BarChart3 className="h-3.5 w-3.5" /> Formal evidence below</span>
          </div>
        </div>
      </div>
    </div>
  );
}

function EvidencePreview() {
  return (
    <div className="landing-product-window landing-evidence-window">
      <WindowChrome title="Strategy evidence" meta="Performance to provenance" />
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
            <p className="landing-preview-kicker">One strategy, one workspace</p>
            <h3>Move from the current target to the evidence behind it.</h3>
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

  useEffect(() => {
    document.documentElement.classList.toggle('dark', theme === 'dark');
    document.title = 'Alpha Engine — Systematic Strategy Console';
    const description = document.querySelector('meta[name="description"]');
    description?.setAttribute('content', 'Monitor governed medium-frequency strategies, inspect target allocations, and drill into performance, risk, holdings, drivers and evidence.');
  }, [theme]);

  return (
    <div className="alpha-landing">
      <header className="landing-nav">
        <Link to="/" className="landing-brand" aria-label="Alpha Engine home">
          <span className="landing-brand-mark"><Orbit className="h-4 w-4" /></span>
          <span><strong>Alpha Engine</strong><small>Systematic strategies</small></span>
        </Link>
        <nav aria-label="Product navigation">
          <a href="#workflow">Workflow</a>
          <a href="#evidence">Evidence</a>
          <a href="https://github.com/liuh886/alpha_engine" target="_blank" rel="noreferrer"><Github className="h-4 w-4" /><span className="sr-only">GitHub</span></a>
          <ThemeButton />
          <Link className="landing-nav-cta" to="/app">Open console <ArrowRight className="h-3.5 w-3.5" /></Link>
        </nav>
      </header>

      <main>
        <section className="landing-hero">
          <div className="landing-hero-copy">
            <h1>Run systematic strategies with the evidence still attached.</h1>
            <p>Alpha Engine turns governed research into a decision-first console for medium-frequency strategies: current state, target allocation, next decision, risk and the evidence behind each model.</p>
            <div className="landing-actions">
              <Link className="landing-primary-action" to="/app">Open Strategy Console <ArrowRight className="h-4 w-4" /></Link>
              <Link className="landing-secondary-action" to="/strategies">View formal strategies</Link>
            </div>
            <p className="landing-trust-line">Read-only · Evidence-governed · No broker execution</p>
          </div>
          <FleetPreview />
        </section>

        <section className="landing-story-section" id="workflow">
          <div className="landing-section-copy">
            <span>01</span>
            <h2>Decision first. Evidence on demand.</h2>
            <p>See what each strategy is doing now, what it targets next, what changed, and when it evaluates again. Only then drill into performance, risk and holdings.</p>
            <Link to="/strategies">Explore strategies <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <FleetPreview />
        </section>

        <section className="landing-story-section landing-story-reverse" id="evidence">
          <div className="landing-section-copy">
            <span>02</span>
            <h2>Every target keeps its research context.</h2>
            <p>Formal Bundle v2 evidence, data lineage, factor drivers and research decisions remain inspectable without turning the normal operating screen into an infrastructure dashboard.</p>
            <Link to="/research">Open research <ArrowRight className="h-4 w-4" /></Link>
          </div>
          <EvidencePreview />
        </section>

        <section className="landing-final-cta">
          <div><h2>Know what the strategy says before reading every artifact.</h2><p>Open the strategy fleet, then drill down only where the decision requires it.</p></div>
          <Link className="landing-primary-action" to="/app">Enter Alpha Engine <ArrowRight className="h-4 w-4" /></Link>
        </section>
      </main>

      <footer className="landing-footer"><p>Alpha Engine</p><p>Governed medium-frequency strategy research and monitoring</p></footer>
    </div>
  );
}
