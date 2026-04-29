import { StrategyProfile } from "@/lib/strategy-store";

function toLines(value: string[]): string {
  return (value || []).join("\n");
}

function fromLines(value: string): string[] {
  return value
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
}

export function StrategyForm({
  profile,
  onChange,
}: {
  profile: StrategyProfile;
  onChange: (next: StrategyProfile) => void;
}) {
  const update = (patch: Partial<StrategyProfile>) => {
    onChange({ ...profile, ...patch });
  };

  return (
    <div className="space-y-6">
      <section className="rounded-lg border p-4 space-y-3">
        <div className="text-sm font-semibold">Meta</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            className="border rounded px-2 py-1"
            placeholder="Name"
            value={profile.meta.name}
            onChange={(e) => update({ meta: { ...profile.meta, name: e.target.value } })}
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Market (cn/us)"
            value={profile.meta.market}
            onChange={(e) => update({ meta: { ...profile.meta, market: e.target.value } })}
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Benchmark (e.g. SPY)"
            value={profile.meta.benchmark}
            onChange={(e) => update({ meta: { ...profile.meta, benchmark: e.target.value } })}
          />
        </div>
      </section>

      <section className="rounded-lg border p-4 space-y-3">
        <div className="text-sm font-semibold">Universe</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            className="border rounded px-2 py-1"
            placeholder="Type (watchlist/custom_list)"
            value={profile.universe.type}
            onChange={(e) =>
              update({ universe: { ...profile.universe, type: e.target.value } })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Min Liquidity"
            type="number"
            value={profile.universe.filters.min_liquidity ?? ""}
            onChange={(e) =>
              update({
                universe: {
                  ...profile.universe,
                  filters: { ...profile.universe.filters, min_liquidity: Number(e.target.value) },
                },
              })
            }
          />
        </div>
        <textarea
          className="border rounded px-2 py-1 w-full h-28"
          placeholder="Custom list (one ticker per line)"
          value={toLines(profile.universe.custom_list)}
          onChange={(e) =>
            update({
              universe: { ...profile.universe, custom_list: fromLines(e.target.value) },
            })
          }
        />
      </section>

      <section className="rounded-lg border p-4 space-y-3">
        <div className="text-sm font-semibold">Model</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            className="border rounded px-2 py-1"
            placeholder="Model Class (LGBModel)"
            value={profile.model.class}
            onChange={(e) => update({ model: { ...profile.model, class: e.target.value } })}
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Learning Rate"
            type="number"
            value={profile.model.kwargs.learning_rate ?? ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  kwargs: { ...profile.model.kwargs, learning_rate: Number(e.target.value) },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Num Leaves"
            type="number"
            value={profile.model.kwargs.num_leaves ?? ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  kwargs: { ...profile.model.kwargs, num_leaves: Number(e.target.value) },
                },
              })
            }
          />
        </div>
        <textarea
          className="border rounded px-2 py-1 w-full h-24"
          placeholder="Label (one per line)"
          value={toLines(profile.model.label)}
          onChange={(e) =>
            update({ model: { ...profile.model, label: fromLines(e.target.value) } })
          }
        />
        <textarea
          className="border rounded px-2 py-1 w-full h-40"
          placeholder="Features (one per line)"
          value={toLines(profile.model.features)}
          onChange={(e) =>
            update({ model: { ...profile.model, features: fromLines(e.target.value) } })
          }
        />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <input
            className="border rounded px-2 py-1"
            placeholder="Train start"
            value={profile.model.train_window.train[0] || ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  train_window: {
                    ...profile.model.train_window,
                    train: [e.target.value, profile.model.train_window.train[1]],
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Train end"
            value={profile.model.train_window.train[1] || ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  train_window: {
                    ...profile.model.train_window,
                    train: [profile.model.train_window.train[0], e.target.value],
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Valid start"
            value={profile.model.train_window.valid[0] || ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  train_window: {
                    ...profile.model.train_window,
                    valid: [e.target.value, profile.model.train_window.valid[1]],
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Valid end"
            value={profile.model.train_window.valid[1] || ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  train_window: {
                    ...profile.model.train_window,
                    valid: [profile.model.train_window.valid[0], e.target.value],
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Test start"
            value={profile.model.train_window.test[0] || ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  train_window: {
                    ...profile.model.train_window,
                    test: [e.target.value, profile.model.train_window.test[1]],
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Test end"
            value={profile.model.train_window.test[1] || ""}
            onChange={(e) =>
              update({
                model: {
                  ...profile.model,
                  train_window: {
                    ...profile.model.train_window,
                    test: [profile.model.train_window.test[0], e.target.value],
                  },
                },
              })
            }
          />
        </div>
      </section>

      <section className="rounded-lg border p-4 space-y-3">
        <div className="text-sm font-semibold">Strategy</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <input
            className="border rounded px-2 py-1"
            placeholder="Buy rule"
            value={profile.strategy.buy_rule}
            onChange={(e) =>
              update({ strategy: { ...profile.strategy, buy_rule: e.target.value } })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Sell rule"
            value={profile.strategy.sell_rule}
            onChange={(e) =>
              update({ strategy: { ...profile.strategy, sell_rule: e.target.value } })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Top K"
            type="number"
            value={profile.strategy.position_rule.topk}
            onChange={(e) =>
              update({
                strategy: {
                  ...profile.strategy,
                  position_rule: {
                    ...profile.strategy.position_rule,
                    topk: Number(e.target.value),
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Drop N"
            type="number"
            value={profile.strategy.position_rule.n_drop}
            onChange={(e) =>
              update({
                strategy: {
                  ...profile.strategy,
                  position_rule: {
                    ...profile.strategy.position_rule,
                    n_drop: Number(e.target.value),
                  },
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Capital"
            type="number"
            value={profile.strategy.capital}
            onChange={(e) =>
              update({
                strategy: { ...profile.strategy, capital: Number(e.target.value) },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Costs (bps)"
            type="number"
            value={profile.strategy.costs_bps}
            onChange={(e) =>
              update({
                strategy: { ...profile.strategy, costs_bps: Number(e.target.value) },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Backtest start"
            value={profile.strategy.backtest_window[0] || ""}
            onChange={(e) =>
              update({
                strategy: {
                  ...profile.strategy,
                  backtest_window: [e.target.value, profile.strategy.backtest_window[1]],
                },
              })
            }
          />
          <input
            className="border rounded px-2 py-1"
            placeholder="Backtest end"
            value={profile.strategy.backtest_window[1] || ""}
            onChange={(e) =>
              update({
                strategy: {
                  ...profile.strategy,
                  backtest_window: [profile.strategy.backtest_window[0], e.target.value],
                },
              })
            }
          />
        </div>
      </section>
    </div>
  );
}
