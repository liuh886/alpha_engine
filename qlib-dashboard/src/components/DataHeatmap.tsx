import { useEffect, useRef, useState, useCallback, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";

interface HeatmapData {
  symbols: string[];
  dates: string[];
  values: (number | null)[][];
}

interface DataHeatmapProps {
  data: HeatmapData;
  feature: string;
}

const CELL_H = 16;
const LABEL_W = 72;
const HEADER_H = 32;
const MIN_CELL_W = 3;

// Coverage mode colors
const COLOR_HAS_DATA = "#22c55e"; // green-500
const COLOR_NO_DATA = "#1a1a1a";

// Value mode: blue colormap
function valueToColor(v: number, min: number, max: number): string {
  if (max === min) return "hsl(220, 60%, 40%)";
  const t = Math.max(0, Math.min(1, (v - min) / (max - min)));
  const hue = 220 - t * 170;
  const sat = 50 + t * 30;
  const light = 20 + t * 40;
  return `hsl(${hue}, ${sat}%, ${light}%)`;
}

export function DataHeatmap({ data, feature }: DataHeatmapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [search, setSearch] = useState("");
  const [scrollTop, setScrollTop] = useState(0);
  const [scrollLeft, setScrollLeft] = useState(0);
  const [containerWidth, setContainerWidth] = useState(800);
  const [hoveredCell, setHoveredCell] = useState<{
    row: number;
    col: number;
    x: number;
    y: number;
  } | null>(null);

  const isCoverage = feature === "close";

  // Compute cell width to fit container, or use min width if too many columns
  const cellW = useMemo(() => {
    const available = containerWidth - LABEL_W;
    const computed = Math.floor(available / data.dates.length);
    return Math.max(MIN_CELL_W, computed);
  }, [containerWidth, data.dates.length]);

  const canvasW = LABEL_W + data.dates.length * cellW;
  const needsHScroll = canvasW > containerWidth;

  // Filter symbols by search
  const filteredIndices = useMemo(() => {
    if (!search.trim()) return data.symbols.map((_, i) => i);
    const q = search.toLowerCase();
    return data.symbols
      .map((sym, i) => (sym.toLowerCase().includes(q) ? i : -1))
      .filter((i) => i >= 0);
  }, [data.symbols, search]);

  const filteredSymbols = useMemo(
    () => filteredIndices.map((i) => data.symbols[i]),
    [filteredIndices, data.symbols]
  );

  const filteredValues = useMemo(
    () => filteredIndices.map((i) => data.values[i]),
    [filteredIndices, data.values]
  );

  // Compute value range for colormap
  const { minVal, maxVal } = useMemo(() => {
    if (isCoverage) return { minVal: 0, maxVal: 1 };
    let min = Infinity,
      max = -Infinity;
    for (const row of filteredValues) {
      if (!row) continue;
      for (const v of row) {
        if (v === null || v === undefined) continue;
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    if (!isFinite(min)) {
      min = 0;
      max = 1;
    }
    return { minVal: min, maxVal: max };
  }, [filteredValues, isCoverage]);

  const totalRows = filteredSymbols.length;
  const totalCols = data.dates.length;
  const canvasH = HEADER_H + totalRows * CELL_H;
  const containerH = containerRef.current?.clientHeight || 500;
  const visibleRows = Math.floor((containerH - HEADER_H) / CELL_H);

  // Observe container width
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    ro.observe(el);
    setContainerWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    const displayW = Math.max(canvasW, containerWidth);
    const displayH = Math.min(canvasH, containerH);

    canvas.width = displayW * dpr;
    canvas.height = displayH * dpr;
    canvas.style.width = `${displayW}px`;
    canvas.style.height = `${displayH}px`;
    ctx.scale(dpr, dpr);

    ctx.fillStyle = "#0a0a0a";
    ctx.fillRect(0, 0, displayW, displayH);

    const startRow = Math.floor(scrollTop / CELL_H);
    const endRow = Math.min(totalRows, startRow + visibleRows + 2);

    // Draw cells
    for (let r = startRow; r < endRow; r++) {
      const y = HEADER_H + r * CELL_H - scrollTop;
      const row = filteredValues[r];
      if (!row) continue;

      for (let c = 0; c < totalCols; c++) {
        const x = LABEL_W + c * cellW;
        if (x + cellW < scrollLeft || x > scrollLeft + containerWidth) continue;

        const v = row[c];
        if (v === null || v === undefined) {
          ctx.fillStyle = COLOR_NO_DATA;
        } else if (isCoverage) {
          ctx.fillStyle = COLOR_HAS_DATA;
        } else {
          ctx.fillStyle = valueToColor(v, minVal, maxVal);
        }
        ctx.fillRect(x, y, cellW - 0.5, CELL_H - 1);
      }
    }

    // Draw row labels
    ctx.fillStyle = "#a1a1aa";
    ctx.font = "11px monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (let r = startRow; r < endRow; r++) {
      const y = HEADER_H + r * CELL_H - scrollTop + CELL_H / 2;
      ctx.fillText(filteredSymbols[r], LABEL_W - 8, y);
    }

    // Draw header (time percentage)
    ctx.fillStyle = "#71717a";
    ctx.font = "10px monospace";
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    const step = Math.max(1, Math.floor(totalCols / 10));
    for (let c = 0; c < totalCols; c += step) {
      const x = LABEL_W + c * cellW;
      const pct = ((c / totalCols) * 100).toFixed(0) + "%";
      ctx.fillText(pct, x, HEADER_H - 6);
    }

    // Hover highlight
    if (hoveredCell) {
      const hx = LABEL_W + hoveredCell.col * cellW;
      const hy = HEADER_H + hoveredCell.row * CELL_H - scrollTop;
      ctx.strokeStyle = "#fff";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(hx - 0.5, hy - 0.5, cellW, CELL_H);
    }
  }, [
    filteredSymbols,
    filteredValues,
    totalCols,
    totalRows,
    scrollTop,
    scrollLeft,
    visibleRows,
    isCoverage,
    minVal,
    maxVal,
    hoveredCell,
    canvasW,
    containerWidth,
    containerH,
    cellW,
  ]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const handleScroll = () => {
      setScrollTop(container.scrollTop);
      setScrollLeft(container.scrollLeft);
    };
    container.addEventListener("scroll", handleScroll, { passive: true });
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const rect = canvasRef.current?.getBoundingClientRect();
      if (!rect) return;
      const x = e.clientX - rect.left + scrollLeft;
      const y = e.clientY - rect.top;

      const col = Math.floor((x - LABEL_W) / cellW);
      const row = Math.floor((y - HEADER_H + scrollTop) / CELL_H);

      if (col >= 0 && col < totalCols && row >= 0 && row < totalRows) {
        setHoveredCell({ row, col, x: e.clientX, y: e.clientY });
      } else {
        setHoveredCell(null);
      }
    },
    [totalCols, totalRows, scrollTop, scrollLeft, cellW]
  );

  const tooltipContent = useMemo(() => {
    if (!hoveredCell) return null;
    const symIdx = filteredIndices[hoveredCell.row];
    const sym = data.symbols[symIdx];
    const date = data.dates[hoveredCell.col];
    const val = data.values[symIdx]?.[hoveredCell.col];
    return { sym, date, val };
  }, [hoveredCell, filteredIndices, data]);

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 mb-2 px-1">
        <div className="relative flex-1 max-w-xs">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter symbols..."
            className="h-8 pl-8 text-xs font-mono"
          />
        </div>
        <span className="text-xs text-muted-foreground font-mono">
          {filteredSymbols.length}/{data.symbols.length}
        </span>
      </div>

      <div
        ref={containerRef}
        className="flex-1 overflow-auto"
        style={{ minHeight: 300 }}
      >
        <canvas
          ref={canvasRef}
          onMouseMove={handleMouseMove}
          onMouseLeave={() => setHoveredCell(null)}
          style={{ display: "block", cursor: "crosshair" }}
        />
      </div>

      {tooltipContent && (
        <div
          className="fixed z-50 pointer-events-none bg-popover border rounded shadow-lg px-3 py-2 text-xs"
          style={{
            left: hoveredCell!.x + 12,
            top: hoveredCell!.y - 10,
          }}
        >
          <div className="font-mono font-bold">{tooltipContent.sym}</div>
          <div className="text-muted-foreground">{tooltipContent.date}</div>
          <div className="mt-1">
            {tooltipContent.val === null || tooltipContent.val === undefined ? (
              <span className="text-red-400">No data</span>
            ) : isCoverage ? (
              <span className="text-green-400">Data present</span>
            ) : (
              <span className="font-mono">
                {feature}:{" "}
                {typeof tooltipContent.val === "number"
                  ? tooltipContent.val.toFixed(4)
                  : tooltipContent.val}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
