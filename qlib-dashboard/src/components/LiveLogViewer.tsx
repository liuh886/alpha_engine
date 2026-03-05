import { useState, useEffect, useRef } from "react";

interface LiveLogViewerProps {
  jobId: string;
  onDone?: () => void;
}

export function LiveLogViewer({ jobId, onDone }: LiveLogViewerProps) {
  const [logs, setLogs] = useState<string[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!jobId) return;

    const eventSource = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/stream`);

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.line) {
        setLogs((prev) => [...prev, data.line]);
      }
    };

    eventSource.addEventListener("done", () => {
      eventSource.close();
      if (onDone) onDone();
    });

    eventSource.addEventListener("error", (e) => {
      console.error("SSE Error:", e);
      eventSource.close();
    });

    return () => {
      eventSource.close();
    };
  }, [jobId]);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  return (
    <div className="rounded-md border bg-black text-green-400 p-2 font-mono text-[10px] h-[300px] flex flex-col">
      <div className="text-gray-500 mb-1 border-b border-gray-800 pb-1">Live Log Stream (Job: {jobId})</div>
      <div className="flex-1 overflow-y-auto" ref={scrollRef}>
        {logs.map((line, i) => (
          <div key={i} className="whitespace-pre-wrap leading-tight py-0.5 border-b border-gray-900/50">
            {line}
          </div>
        ))}
        {logs.length === 0 && <div className="text-gray-700 animate-pulse italic">Waiting for logs...</div>}
      </div>
    </div>
  );
}
