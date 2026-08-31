import React from 'react';
import { CheckCircle2, Clock, AlertCircle, ShieldCheck, Database, Layers, GitMerge, Cpu, ArrowRight } from 'lucide-react';
import { DAGNodeState } from '../../types/batch';

interface LangGraphDAGVisualizerProps {
  currentNodeIndex: number;
  status: 'IDLE' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  progressPercent: number;
}

export const LangGraphDAGVisualizer: React.FC<LangGraphDAGVisualizerProps> = ({
  currentNodeIndex,
  status,
  progressPercent,
}) => {
  const dagNodes: DAGNodeState[] = [
    { id: 'node_1', label: '1. Ingestion & Provenance', sublabel: 'SHA-256 Hash Seals', status: 'pending' },
    { id: 'node_2', label: '2. Normalization & Quantization', sublabel: 'Paise Minor Unit Grid', status: 'pending' },
    { id: 'node_3', label: '3. Multi-Pass Match Engine', sublabel: 'P0-P4 Hungarian Solver', status: 'pending' },
    { id: 'node_4', label: '4. Exception Triage & RCA', sublabel: 'Groq 120B Micro LLM', status: 'pending' },
    { id: 'node_4b', label: '4b. Hard Mathematical Gate', sublabel: 'Deterministic Math Proof', status: 'pending' },
    { id: 'node_5', label: '5. Maker-Checker Routing', sublabel: 'SOD Dual-Control Queue', status: 'pending' },
    { id: 'node_6', label: '6. Cryptographic Audit Seal', sublabel: 'Sequential Block Ledger', status: 'pending' },
  ];

  return (
    <div className="rounded-2xl border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-5 shadow-xl space-y-4 font-mono text-xs">
      <div className="flex items-center justify-between">
        <div>
          <span className="text-[10px] text-emerald-400 font-bold uppercase tracking-wider">
            LANGGRAPH STATE MACHINE VISUALIZER
          </span>
          <h3 className="text-sm font-bold text-[var(--text-primary)] font-sans mt-0.5">
            Deterministic Reconciliation & Governance DAG
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[11px] text-[var(--text-muted)]">Progress:</span>
          <span className="text-xs font-bold text-emerald-400 tabular-nums">{progressPercent}%</span>
        </div>
      </div>

      {/* Progress Track */}
      <div className="h-1.5 w-full bg-[var(--bg-card)] rounded-full overflow-hidden">
        <div
          className="h-full bg-gradient-to-r from-emerald-500 via-sky-400 to-emerald-400 transition-all duration-300 shadow-sm"
          style={{ width: `${Math.max(5, progressPercent)}%` }}
        />
      </div>

      {/* DAG 7-Node Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-2.5 pt-2">
        {dagNodes.map((node, idx) => {
          const isCurrent = status === 'RUNNING' && currentNodeIndex === idx;
          const isCompleted = status === 'COMPLETED' || (status === 'RUNNING' && idx < currentNodeIndex);

          let borderStyle = 'border-[var(--border-subtle)] bg-[var(--bg-card)] text-[var(--text-muted)]';
          if (isCurrent) {
            borderStyle = 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300 shadow-md shadow-emerald-500/10 animate-pulse';
          } else if (isCompleted) {
            borderStyle = 'border-emerald-500/30 bg-emerald-500/5 text-emerald-400';
          }

          return (
            <div
              key={node.id}
              className={`p-3 rounded-xl border flex flex-col justify-between transition-all min-h-[90px] ${borderStyle}`}
            >
              <div>
                <div className="text-[9px] font-bold text-[var(--text-dim)] uppercase">NODE 0{idx + 1}</div>
                <div className="font-bold text-[var(--text-primary)] text-[11px] mt-0.5 leading-tight font-sans">
                  {node.label}
                </div>
                <div className="text-[9px] text-[var(--text-muted)] mt-1">{node.sublabel}</div>
              </div>

              <div className="mt-2 pt-1 border-t border-[var(--border-subtle)] flex items-center justify-between text-[10px]">
                {isCompleted ? (
                  <span className="text-emerald-400 flex items-center gap-1 font-bold">
                    <CheckCircle2 className="h-3 w-3" /> Sealed
                  </span>
                ) : isCurrent ? (
                  <span className="text-sky-400 flex items-center gap-1 font-bold">
                    <Clock className="h-3 w-3 animate-spin" /> Processing
                  </span>
                ) : (
                  <span className="text-[var(--text-dim)]">Waiting</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
