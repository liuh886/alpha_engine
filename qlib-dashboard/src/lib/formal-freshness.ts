export type FormalFreshnessStatus = 'current' | 'stale' | 'blocked' | 'unknown';

export interface FormalFreshnessPolicy {
  schema_version: string;
  cutoff_policy: 'latest_completed_trading_session';
  markets: Record<string, string>;
  next_session_close_utc: Record<string, string>;
  research_only: true;
  trade_ready: false;
}

export interface FormalFreshnessSnapshot {
  status: FormalFreshnessStatus;
  policy: FormalFreshnessPolicy | null;
  staleMarkets: string[];
  checkedAt: string;
  message: string;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

export function parseFormalFreshnessPolicy(value: unknown): FormalFreshnessPolicy {
  if (!isObject(value)
    || value.cutoff_policy !== 'latest_completed_trading_session'
    || value.research_only !== true
    || value.trade_ready !== false
    || !isObject(value.markets)
    || !isObject(value.next_session_close_utc)) {
    throw new Error('Formal freshness policy contract is invalid.');
  }
  const markets = Object.fromEntries(Object.entries(value.markets).map(([key, item]) => [key, String(item)]));
  const closes = Object.fromEntries(Object.entries(value.next_session_close_utc).map(([key, item]) => [key, String(item)]));
  if (Object.keys(markets).length === 0 || Object.keys(markets).some((key) => !(key in closes))) {
    throw new Error('Formal freshness market/close bindings are incomplete.');
  }
  for (const [market, close] of Object.entries(closes)) {
    if (!(market in markets) || Number.isNaN(Date.parse(close))) {
      throw new Error(`Formal freshness close is invalid: ${market}.`);
    }
  }
  return {
    schema_version: String(value.schema_version ?? ''),
    cutoff_policy: 'latest_completed_trading_session',
    markets,
    next_session_close_utc: closes,
    research_only: true,
    trade_ready: false,
  };
}

export function classifyFormalFreshness(
  policy: FormalFreshnessPolicy,
  now: Date = new Date(),
): FormalFreshnessSnapshot {
  const staleMarkets = Object.entries(policy.next_session_close_utc)
    .filter(([, close]) => now.getTime() >= Date.parse(close))
    .map(([market]) => market)
    .sort();
  if (staleMarkets.length > 0) {
    return {
      status: 'stale',
      policy,
      staleMarkets,
      checkedAt: now.toISOString(),
      message: `Published formal evidence is older than the latest completed ${staleMarkets.map((value) => value.toUpperCase()).join(' / ')} session.`,
    };
  }
  return {
    status: 'current',
    policy,
    staleMarkets: [],
    checkedAt: now.toISOString(),
    message: 'Published formal evidence matches the declared latest completed sessions.',
  };
}

function assetUrl(path: string): string {
  const base = import.meta.env.BASE_URL.endsWith('/') ? import.meta.env.BASE_URL : `${import.meta.env.BASE_URL}/`;
  return `${base}data/formal-model-runs/${path}`;
}

export async function fetchFormalFreshness(now: Date = new Date()): Promise<FormalFreshnessSnapshot> {
  try {
    const response = await fetch(assetUrl('freshness.json'), { cache: 'no-cache' });
    if (!response.ok) {
      return {
        status: 'unknown',
        policy: null,
        staleMarkets: [],
        checkedAt: now.toISOString(),
        message: `Formal freshness policy is unavailable (${response.status}).`,
      };
    }
    try {
      const policy = parseFormalFreshnessPolicy(await response.json() as unknown);
      return classifyFormalFreshness(policy, now);
    } catch (error) {
      return {
        status: 'blocked',
        policy: null,
        staleMarkets: [],
        checkedAt: now.toISOString(),
        message: error instanceof Error ? error.message : 'Formal freshness policy is invalid.',
      };
    }
  } catch (error) {
    return {
      status: 'unknown',
      policy: null,
      staleMarkets: [],
      checkedAt: now.toISOString(),
      message: error instanceof Error ? error.message : 'Formal freshness request failed.',
    };
  }
}
