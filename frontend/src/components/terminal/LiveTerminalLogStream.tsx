import React, { useRef, useEffect } from 'react';
import { Terminal as TerminalIcon } from 'lucide-react';

interface LiveTerminalLogStreamProps {
  logs: string[];
}

export const LiveTerminalLogStream: React.FC<LiveTerminalLogStreamProps> = ({ logs }) => {
  const terminalEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [logs]);

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[#05080f] overflow-hidden shadow-2xl font-mono text-xs">
      <div className="bg-[var(--bg-surface)] px-4 py-2.5 border-b border-[var(--border-subtle)] flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-2.5 h-2.5 rounded-full bg-red-500/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-amber-500/60" />
          <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/60" />
          <span className="text-[var(--text-muted)] text-[11px] ml-2 flex items-center gap-1.5 font-bold">
            <TerminalIcon className="h-3.5 w-3.5 text-emerald-400" />
            Deterministic Execution Terminal Stream
          </span>
        </div>
        <div className="flex items-center gap-1.5 text-[10px] text-emerald-400 font-bold">
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
          <span>PAISE-ACCURATE LOGS</span>
        </div>
      </div>

      <div className="p-4 h-52 overflow-y-auto space-y-1.5 text-[var(--text-secondary)]">
        {logs.length === 0 ? (
          <div className="text-[var(--text-dim)] italic">No execution logs yet. Ingest feeds to begin matching.</div>
        ) : (
          logs.map((log, idx) => (
            <div key={idx} className="leading-relaxed">
              {log}
            </div>
          ))
        )}
        <div ref={terminalEndRef} />
      </div>
    </div>
  );
};
