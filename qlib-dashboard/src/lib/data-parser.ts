export interface BacktestData {
  meta: {
    start: string;
    end: string;
    benchmark: string;
    market?: string;
    generated_at?: string;
  };
  metrics: Record<string, number>;
  report: any[];
  positions: any[];
  featureImportance: Record<string, number>;
  indicators: Record<string, any>;
}

export interface ModelData {
  id: string;
  name: string;
  market: string;
  date: string;
  params: Record<string, any>;
  backtest: BacktestData;
}

export function parseQlibData(json: any): ModelData[] {
  if (!json || !json.models) return [];

  return json.models.map((m: any) => {
    // Extract metrics from indicators if available (skip empty objects)
    const metrics: Record<string, number | null> = {};
    const indicators = m.data?.indicators;
    if (indicators && typeof indicators === "object" && Object.keys(indicators).length > 0) {
      metrics["Total Return"] = indicators.total_return ?? null;
      metrics["Annualized Return"] = indicators.annual_return ?? null;
      metrics["Sharpe Ratio"] = indicators.sharpe ?? null;
      metrics["Information Ratio"] = indicators.information_ratio ?? null;
      metrics["Max Drawdown"] = indicators.max_drawdown ?? null;
      metrics["Annualized Volatility"] = indicators.annual_volatility ?? null;
    }

    // Map report_normal to report array
    const report: any[] = [];
    if (m.data && m.data.report_normal && m.data.report_normal.columns && m.data.report_normal.index) {
      const cols = m.data.report_normal.columns;
      const data = m.data.report_normal.data;
      const index = m.data.report_normal.index;

      index.forEach((date: string, i: number) => {
        const row: any = { date: date.split('T')[0] };
        cols.forEach((col: string, j: number) => {
          row[col] = data[i][j];
        });
        report.push(row);
      });
    }

    // Map positions_normal
    const positions = m.data?.positions_normal || [];

    return {
      id: m.id,
      name: m.name,
      market: m.market,
      date: m.date,
      params: m.params || {},
      backtest: {
        meta: {
          start: report.length > 0 ? report[0].date : "N/A",
          end: report.length > 0 ? report[report.length - 1].date : "N/A",
          benchmark: m.market === "us" ? "Nasdaq 100" : "CSI 300",
          market: m.market,
          generated_at: json.generated_at
        },
        metrics,
        report,
        positions,
        featureImportance: m.data?.sig_analysis?.feature_importance || {},
        indicators: m.data?.indicators || {}
      }
    };
  });
}
