import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  buildDerivedMetricPublication,
  canonicalJson,
  DerivedMetricPublicationError,
  publishDerivedMetrics,
  readDerivedArtifacts,
  sha256Hex,
} from './public-derived-metrics.mjs';

const PERFORMANCE_SHA = '7e4d27ef0b698a2cbc66ab5018b116d477e9bbd7c89bbaef2d37afff843859c7';
const MANIFEST_SHA = 'e822b9e3001fc780183a7a0230c807652f5e03941f8e87bc23281d77daf988dc';
const BUNDLE_ID = '27bc3a6d675b8e3a2a935ec2089a0c8960f2467227863e97bcc9a6983a07bc7e';
const GENERATED_AT = '2026-11-12T04:01:28Z';

function artifactFixture() {
  return {
    benchmark: {
      comparability_id: 'qqq',
      declared_identity: 'QQQ',
      series_semantics: 'adjusted_open_to_next_adjusted_open',
      source_identity: { provider: 'yfinance', rows: 4241 },
    },
    boundaries: {
      descriptive_historical_metric: true,
      formal_catalog_modified: false,
      live_signal: false,
      pit_certified: false,
      research_only: true,
      sealed_formal_evidence_rewritten: false,
      source_registry_pins_modified: false,
      trade_ready: false,
    },
    derivation_id: 'fixture_excess_v1',
    evidence_type: 'derived_formal_benchmark_excess',
    inputs: [
      {
        bytes: 3331,
        manifest_section: null,
        path: 'data/research/formal_model_runs/qqq_rotation/fixture/manifest.json',
        role: 'formal_manifest',
        sha256: MANIFEST_SHA,
      },
      {
        bytes: 389313,
        manifest_section: 'performance',
        path: 'data/research/formal_model_runs/qqq_rotation/fixture/performance.json',
        role: 'formal_performance',
        sha256: PERFORMANCE_SHA,
      },
    ],
    method: {
      compounding: 'geometric',
      formula: '(1 + strategy_cumulative_return) / (1 + benchmark_cumulative_return) - 1',
      method_id: 'compounded_relative_excess',
    },
    result: {
      benchmark_cumulative_return: 0.6323106782547736,
      excess_return: 0.16979364938155483,
      strategy_cumulative_return: 0.9094666652401326,
    },
    schema_version: '1.0',
    strategy: {
      bundle_id: BUNDLE_ID,
      generated_at: GENERATED_AT,
      manifest_path: 'data/research/formal_model_runs/qqq_rotation/fixture/manifest.json',
      manifest_sha256: MANIFEST_SHA,
      model_family_id: 'qqq_rotation',
      model_version_id: 'fixture_model_v1',
      run_id: 'fixture_model_v1-through-2026_11_11',
    },
    window: {
      declared_end: '2026-11-10',
      declared_start: '2024-01-30',
      evidence_cutoff: '2026-11-11',
      observation_count: 699,
      observed_end: '2026-11-10',
      observed_start: '2024-01-30',
      trace_frequency: 'daily_open_to_open',
    },
  };
}

function formalCatalogFixture() {
  return {
    channel: 'formal',
    generated_at: '2026-11-12T11:14:39Z',
    records: [
      {
        bundle_id: BUNDLE_ID,
        evidence_cutoff: '2026-11-11',
        manifest_path: 'qqq_rotation/fixture/manifest.json',
        manifest_sha256: MANIFEST_SHA,
        model_family_id: 'qqq_rotation',
        model_kind: 'rules_based_allocation',
        model_version_id: 'fixture_model_v1',
        publication_status: 'accepted_formal_baseline',
        run_id: 'fixture_model_v1-through-2026_11_11',
      },
    ],
    research_only: true,
    schema_version: '2.0.0',
    trade_ready: false,
  };
}

function manifestFixture() {
  return {
    bundle_id: BUNDLE_ID,
    evidence_cutoff: '2026-11-11',
    model_family_id: 'qqq_rotation',
    model_kind: 'rules_based_allocation',
    model_version_id: 'fixture_model_v1',
    publication_channel: 'formal',
    publication_status: 'accepted_formal_baseline',
    research_only: true,
    run_id: 'fixture_model_v1-through-2026_11_11',
    schema_version: '2.0.0',
    sections: [
      {
        availability_status: 'available',
        byte_size: 389313,
        media_type: 'application/json',
        path: 'performance.json',
        reason: null,
        required_for_model_kind: true,
        section_id: 'performance',
        sha256: PERFORMANCE_SHA,
      },
    ],
    trade_ready: false,
  };
}

function manifestsFixture() {
  return new Map([[MANIFEST_SHA, manifestFixture()]]);
}

function build(artifacts, options = {}) {
  return buildDerivedMetricPublication({
    artifacts,
    formalCatalog: formalCatalogFixture(),
    manifests: manifestsFixture(),
    ...options,
  });
}

function expectRejection(mutate, pattern) {
  const artifact = artifactFixture();
  mutate(artifact);
  expect(() => build([artifact])).toThrow(DerivedMetricPublicationError);
  expect(() => build([artifact])).toThrow(pattern);
}

describe('buildDerivedMetricPublication', () => {
  it('publishes canonical artifact bytes and a minimal deterministic catalog', () => {
    const publication = build([artifactFixture()]);
    expect(publication.files).toHaveLength(1);
    const file = publication.files[0];
    expect(file.path).toBe('derived-metrics/fixture_excess_v1.json');
    expect(file.encoded).toBe(canonicalJson(artifactFixture()));
    expect(file.encoded.endsWith('\n')).toBe(true);
    expect(JSON.parse(file.encoded)).toEqual(artifactFixture());
    expect(file.sha256).toBe(sha256Hex(file.encoded));
    expect(file.sha256).toBe(createHash('sha256').update(file.encoded).digest('hex'));
    expect(file.byte_size).toBe(Buffer.byteLength(file.encoded, 'utf8'));

    expect(publication.catalog).toEqual({
      schema_version: 'derived_metric_catalog_v1',
      research_only: true,
      trade_ready: false,
      generated_at: GENERATED_AT,
      entries: [
        {
          derivation_id: 'fixture_excess_v1',
          evidence_type: 'derived_formal_benchmark_excess',
          model_version_id: 'fixture_model_v1',
          run_id: 'fixture_model_v1-through-2026_11_11',
          manifest_sha256: MANIFEST_SHA,
          path: 'derived-metrics/fixture_excess_v1.json',
          sha256: file.sha256,
          byte_size: file.byte_size,
        },
      ],
    });
    expect(Object.keys(publication.catalog.entries[0]).sort()).toEqual([
      'byte_size',
      'derivation_id',
      'evidence_type',
      'manifest_sha256',
      'model_version_id',
      'path',
      'run_id',
      'sha256',
    ]);
    expect(publication.catalogEncoded).toBe(canonicalJson(publication.catalog));
  });

  it('is byte-deterministic across repeated builds and key ordering', () => {
    const first = build([artifactFixture()]);
    const second = build([artifactFixture()]);
    const shuffled = Object.fromEntries(Object.entries(artifactFixture()).reverse());
    const third = build([shuffled]);
    expect(second.files[0].encoded).toBe(first.files[0].encoded);
    expect(third.files[0].encoded).toBe(first.files[0].encoded);
    expect(second.catalogEncoded).toBe(first.catalogEncoded);
    expect(third.catalogEncoded).toBe(first.catalogEncoded);
  });

  it('ignores a JSON artifact with another evidence type', () => {
    const publication = build([
      { evidence_type: 'retained_summary_metric', derivation_id: 'unrelated' },
      artifactFixture(),
    ]);
    expect(publication.files).toHaveLength(1);
    expect(publication.catalog.entries).toHaveLength(1);
  });

  it.each([
    ['research_only false', (artifact) => { artifact.boundaries.research_only = false; }, /research_only/],
    ['trade_ready true', (artifact) => { artifact.boundaries.trade_ready = true; }, /trade_ready/],
    ['descriptive flag false', (artifact) => { artifact.boundaries.descriptive_historical_metric = false; }, /descriptive_historical_metric/],
    ['live signal true', (artifact) => { artifact.boundaries.live_signal = true; }, /live_signal/],
    ['schema version', (artifact) => { artifact.schema_version = '2.0'; }, /schema_version/],
  ])('rejects a %s boundary/schema violation', (_label, mutate, pattern) => {
    expectRejection(mutate, pattern);
  });

  it('rejects an incomplete strategy identity', () => {
    expectRejection((artifact) => { delete artifact.strategy.run_id; }, /strategy\.run_id/);
    expectRejection((artifact) => { artifact.strategy.manifest_sha256 = 'not-a-digest'; }, /manifest_sha256/);
    expectRejection((artifact) => { artifact.strategy.model_family_id = ''; }, /model_family_id/);
  });

  it('rejects a wrong derivation method', () => {
    expectRejection((artifact) => { artifact.method.method_id = 'arithmetic_difference'; }, /method\.method_id/);
  });

  it('rejects non-finite results and unusable cumulative returns', () => {
    expectRejection((artifact) => { artifact.result.excess_return = Number.POSITIVE_INFINITY; }, /finite number/);
    expectRejection((artifact) => { artifact.result.strategy_cumulative_return = Number.NaN; }, /finite number/);
    expectRejection((artifact) => { artifact.result.benchmark_cumulative_return = -1; }, /exceed -1/);
  });

  it('rejects a compounded excess that does not reconcile', () => {
    expectRejection(
      (artifact) => { artifact.result.excess_return += 1e-6; },
      /does not reconcile/,
    );
  });

  it('rejects a performance input SHA that differs from the public manifest', () => {
    expectRejection(
      (artifact) => { artifact.inputs[1].sha256 = 'd'.repeat(64); },
      /formal_performance input SHA/,
    );
    expectRejection(
      (artifact) => { artifact.inputs[1].manifest_section = 'summary'; },
      /manifest_section=performance/,
    );
  });

  it('rejects an unavailable public formal performance section', () => {
    const manifest = manifestFixture();
    manifest.sections[0].availability_status = 'not_retained';
    manifest.sections[0].sha256 = null;
    expect(() => build([artifactFixture()], {
      manifests: new Map([[MANIFEST_SHA, manifest]]),
    })).toThrow(/performance section is unavailable/);
  });

  it('rejects a derivation without a matching public formal run', () => {
    expect(() => build([artifactFixture()], {
      formalCatalog: { ...formalCatalogFixture(), records: [] },
    })).toThrow(/matches 0 public formal catalog records/);
  });

  it('rejects private and operational keys at any depth', () => {
    expectRejection((artifact) => { artifact.benchmark.operating_state = 'private'; }, /operating_state/);
    expectRejection((artifact) => { artifact.benchmark.base_QQQ_weight = 0.42; }, /base_QQQ_weight/);
    expectRejection((artifact) => { artifact.strategy.trades = [{ action: 'BUY' }]; }, /trades/);
    expectRejection((artifact) => { artifact.inputs[0].decision_reason = 'hold'; }, /decision_reason/);
  });

  it('rejects a malformed window', () => {
    expectRejection((artifact) => { artifact.window.observation_count = 0; }, /observation_count/);
    expectRejection((artifact) => { artifact.window.observed_end = '2026-02-30'; }, /observed_end/);
    expectRejection((artifact) => { artifact.window.declared_start = '2024-1-30'; }, /declared_start/);
  });

  it('rejects duplicate derivation ids', () => {
    expect(() => build([artifactFixture(), artifactFixture()])).toThrow(/duplicate derivation_id/);
  });

  it('writes a deterministic empty catalog when no derived artifacts exist', () => {
    const publication = build([]);
    expect(publication.files).toEqual([]);
    expect(publication.catalog).toEqual({
      schema_version: 'derived_metric_catalog_v1',
      research_only: true,
      trade_ready: false,
      generated_at: formalCatalogFixture().generated_at,
      entries: [],
    });
    expect(publication.catalogEncoded).toBe(canonicalJson(publication.catalog));
  });
});

describe('readDerivedArtifacts', () => {
  it('returns only derived excess artifacts and ignores other JSON files', async () => {
    const root = await mkdtemp(join(tmpdir(), 'derived-source-'));
    try {
      await writeFile(join(root, 'fixture.json'), JSON.stringify(artifactFixture()), 'utf8');
      await writeFile(join(root, 'other.json'), JSON.stringify({ evidence_type: 'other' }), 'utf8');
      await writeFile(join(root, 'readme.txt'), 'ignored', 'utf8');
      const artifacts = await readDerivedArtifacts(root);
      expect(artifacts).toHaveLength(1);
      expect(artifacts[0].derivation_id).toBe('fixture_excess_v1');
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it('returns an empty list when the source directory is absent', async () => {
    expect(await readDerivedArtifacts(join(tmpdir(), 'missing-derived-source-directory'))).toEqual([]);
  });

  it('fails closed on malformed JSON', async () => {
    const root = await mkdtemp(join(tmpdir(), 'derived-source-bad-'));
    try {
      await writeFile(join(root, 'bad.json'), '{ not json', 'utf8');
      await expect(readDerivedArtifacts(root)).rejects.toThrow(DerivedMetricPublicationError);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});

describe('publishDerivedMetrics', () => {
  it('writes a deterministic empty catalog when the derived directory is absent', async () => {
    const root = await mkdtemp(join(tmpdir(), 'derived-publish-'));
    try {
      const dashboardRoot = join(root, 'dashboard');
      const formalRoot = join(dashboardRoot, 'public', 'data', 'formal-model-runs');
      await mkdir(formalRoot, { recursive: true });
      await writeFile(join(formalRoot, 'catalog.json'), JSON.stringify(formalCatalogFixture()), 'utf8');

      const first = await publishDerivedMetrics({
        repositoryRoot: join(root, 'repository'),
        dashboardRoot,
      });
      const catalogPath = join(dashboardRoot, 'public', 'data', 'derived-metrics', 'catalog.json');
      const written = JSON.parse(await readFile(catalogPath, 'utf8'));
      expect(first.files).toEqual([]);
      expect(written).toEqual({
        schema_version: 'derived_metric_catalog_v1',
        research_only: true,
        trade_ready: false,
        generated_at: formalCatalogFixture().generated_at,
        entries: [],
      });

      const second = await publishDerivedMetrics({
        repositoryRoot: join(root, 'repository'),
        dashboardRoot,
      });
      expect(second.catalogEncoded).toBe(first.catalogEncoded);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });
});
