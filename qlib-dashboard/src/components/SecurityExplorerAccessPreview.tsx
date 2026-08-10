import { Activity, CandlestickChart, LockKeyhole, Search, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';

const CANDLE_HEIGHTS = [34, 52, 40, 66, 48, 74, 58, 86, 68, 78, 60, 92, 72, 84, 64, 88];

export function SecurityExplorerAccessPreview({ openAccount }: { openAccount: () => void }) {
  return (
    <div className="mx-auto max-w-[1180px] space-y-6 pb-16">
      <section className="grid gap-7 border-b pb-7 lg:grid-cols-[minmax(0,0.9fr)_minmax(520px,1.1fr)] lg:items-center">
        <div className="max-w-xl">
          <div className="flex items-center gap-2 text-sm font-semibold text-primary">
            <CandlestickChart className="h-4 w-4" />
            Security Explorer
          </div>
          <h1 className="mt-3 text-3xl font-black tracking-tight md:text-5xl">
            Sign in to view model trade signals on the price chart.
          </h1>
          <p className="mt-4 text-sm leading-relaxed text-muted-foreground md:text-base">
            Security Explorer combines governed price history with formal model actions, BOLL / MACD / RSI studies and retained factor evidence. The preview below is illustrative; account access unlocks the interactive evidence surface.
          </p>
          <Button className="mt-6" onClick={openAccount}>Sign in to open Security Explorer</Button>
          <p className="mt-3 text-xs text-muted-foreground">A free signed-in AlphaEngine account is sufficient. Pro is not required.</p>
        </div>

        <div className="relative overflow-hidden rounded-2xl border bg-card shadow-sm" aria-label="Illustrative Security Explorer preview">
          <div className="flex items-center justify-between border-b bg-muted/20 px-4 py-3">
            <div>
              <p className="font-mono text-sm font-semibold">QQQ</p>
              <p className="text-[11px] text-muted-foreground">Illustrative chart preview</p>
            </div>
            <div className="flex items-center gap-2 text-[10px] font-semibold text-muted-foreground">
              <span>BOLL</span><span>MACD</span><span>RSI</span>
            </div>
          </div>

          <div className="relative h-[300px] overflow-hidden bg-gradient-to-b from-background to-muted/20 px-5 pb-5 pt-6">
            <div className="absolute inset-x-5 top-[34%] border-t border-dashed border-primary/25" />
            <div className="absolute inset-x-5 top-[58%] border-t border-dashed border-muted-foreground/20" />
            <div className="absolute left-[45%] top-[27%] z-10 rounded-md border border-emerald-500/30 bg-background/95 px-2 py-1 text-[10px] font-bold text-emerald-700 shadow-sm dark:text-emerald-300">BUY</div>
            <div className="absolute right-[17%] top-[43%] z-10 rounded-md border border-rose-500/30 bg-background/95 px-2 py-1 text-[10px] font-bold text-rose-700 shadow-sm dark:text-rose-300">REDUCE</div>

            <div className="flex h-[205px] items-end gap-2" aria-hidden="true">
              {CANDLE_HEIGHTS.map((height, index) => {
                const rising = index % 4 !== 1;
                return (
                  <div key={`${height}-${index}`} className="relative flex h-full flex-1 items-end justify-center">
                    <span className={`absolute bottom-[${Math.max(4, height - 14)}px] h-[${height + 20}px] w-px ${rising ? 'bg-emerald-500/55' : 'bg-rose-500/55'}`} />
                    <span
                      className={rising ? 'w-full max-w-[10px] rounded-[2px] bg-emerald-500/75' : 'w-full max-w-[10px] rounded-[2px] bg-rose-500/75'}
                      style={{ height: `${height}px` }}
                    />
                  </div>
                );
              })}
            </div>

            <div className="mt-5 grid grid-cols-[1fr_auto] items-center gap-4 border-t pt-4">
              <div className="flex h-10 items-end gap-1" aria-hidden="true">
                {[9, 18, 12, 24, 16, 28, 21, 31, 18, 24, 14, 26, 20, 29, 17, 23].map((height, index) => (
                  <span key={`${height}-${index}`} className="flex-1 rounded-t bg-primary/30" style={{ height: `${height}px` }} />
                ))}
              </div>
              <span className="text-[10px] font-semibold text-muted-foreground">MACD</span>
            </div>

            <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-background/25 via-transparent to-transparent" />
            <div className="absolute inset-0 flex items-center justify-center bg-background/5 backdrop-blur-[0.35px]">
              <div className="rounded-full border bg-background/90 p-3 shadow-sm"><LockKeyhole className="h-5 w-5 text-primary" /></div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <div className="rounded-xl border bg-card p-5">
          <CandlestickChart className="h-5 w-5 text-primary" />
          <h2 className="mt-4 text-sm font-semibold">Trade markers in context</h2>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">See retained formal BUY, SELL, INCREASE and DECREASE events directly against the security price history.</p>
        </div>
        <div className="rounded-xl border bg-card p-5">
          <Activity className="h-5 w-5 text-primary" />
          <h2 className="mt-4 text-sm font-semibold">Technical and factor studies</h2>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Switch BOLL, MACD, RSI and published canonical factor panes without leaving the security view.</p>
        </div>
        <div className="rounded-xl border bg-card p-5">
          <ShieldCheck className="h-5 w-5 text-primary" />
          <h2 className="mt-4 text-sm font-semibold">Governed evidence boundary</h2>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Every displayed action remains tied to retained model and provider evidence rather than browser-reconstructed signals.</p>
        </div>
      </section>

      <section className="flex items-center gap-3 rounded-xl border bg-muted/20 p-4 text-sm text-muted-foreground">
        <Search className="h-4 w-4 shrink-0 text-primary" />
        Search US and CN securities after sign-in, then inspect price, model actions and factor evidence in one place.
      </section>
    </div>
  );
}
