import type { BenchmarkOption } from './performanceBenchmarks';

const PRESET_ORDER = ['csi300', 'qqq', 'tqqq', 'cgdv'];

function optionOrder(option: BenchmarkOption): [number, string] {
  const identity = option.label.toLowerCase().replace(/[^a-z0-9]+/g, '');
  const canonical = ['csi300', '000300', '000300sh', 'sh000300'].includes(identity) ? 'csi300' : identity;
  const index = PRESET_ORDER.indexOf(canonical);
  return [index >= 0 ? index : PRESET_ORDER.length, option.label];
}

export function buildPerformanceComparisonOptions(retained: BenchmarkOption[]): BenchmarkOption[] {
  return [...retained].sort((left, right) => {
    const [leftPreset, leftLabel] = optionOrder(left);
    const [rightPreset, rightLabel] = optionOrder(right);
    return leftPreset - rightPreset || leftLabel.localeCompare(rightLabel);
  });
}
