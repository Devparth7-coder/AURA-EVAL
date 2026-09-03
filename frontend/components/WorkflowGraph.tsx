'use client';

/**
 * Visual workflow editor / inspector (§14). Renders the LangGraph topology
 * returned by the API and annotates each node with live execution stats.
 */
import { useCallback, useMemo } from 'react';
import ReactFlow, {
  Background, BackgroundVariant, Controls, Handle, MarkerType, Position,
  type Edge, type Node, type NodeProps, type OnInit,
} from 'reactflow';
import 'reactflow/dist/style.css';
import { cn, fmt } from '@/lib/utils';
import type { GraphEdge, GraphNode, NodeStats } from '@/lib/types';

const LAYOUT: Record<string, { x: number; y: number }> = {
  planner: { x: 340, y: 0 },
  generator: { x: 340, y: 110 },
  dispatch: { x: 340, y: 220 },
  critic: { x: 340, y: 340 },
  refiner: { x: 60, y: 340 },
  approval: { x: 620, y: 340 },
  human_gate: { x: 620, y: 450 },
  fail_sample: { x: 60, y: 450 },
  dataset_builder: { x: 340, y: 570 },
  export: { x: 340, y: 680 },
};

const TONE: Record<string, string> = {
  planner: 'border-violet/40', generator: 'border-accent/40', dispatch: 'border-line',
  critic: 'border-accent/50', refiner: 'border-warn/40', approval: 'border-ok/40',
  human_gate: 'border-violet/40', fail_sample: 'border-danger/40',
  dataset_builder: 'border-ok/40', export: 'border-line',
};

export interface AgentNodeData {
  label: string;
  description: string;
  stats?: NodeStats;
  active?: boolean;
  onSelect?: (id: string) => void;
  nodeId: string;
  selected?: boolean;
}

function AgentNode({ data }: NodeProps<AgentNodeData>) {
  const s = data.stats;
  const failed = (s?.errors ?? 0) > 0;
  return (
    <button
      onClick={() => data.onSelect?.(data.nodeId)}
      className={cn(
        'w-[188px] rounded-xl border bg-base-900 p-3 text-left transition-all duration-200',
        TONE[data.nodeId] || 'border-line',
        data.active && 'animate-pulse-ring border-accent bg-accent/10',
        data.selected && 'ring-1 ring-accent/60',
        'hover:border-slate-500',
      )}
    >
      <Handle type="target" position={Position.Top} className="!h-1.5 !w-1.5" />
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-semibold uppercase tracking-wide text-slate-200">
          {data.label}
        </span>
        <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full',
          failed ? 'bg-danger' : s?.calls ? 'bg-ok' : 'bg-slate-700')} />
      </div>
      <p className="mt-1 line-clamp-2 text-[10px] leading-snug text-slate-500">{data.description}</p>
      {s && s.calls > 0 && (
        <div className="mt-2 flex flex-wrap gap-x-2.5 gap-y-0.5 border-t border-line pt-1.5 font-mono text-[10px] text-slate-500">
          <span>{s.calls}×</span>
          <span>{fmt.ms(s.avg_latency_ms)}</span>
          {s.tokens > 0 && <span>{fmt.tokens(s.tokens)}t</span>}
          {s.errors > 0 && <span className="text-danger">{s.errors} err</span>}
        </div>
      )}
      <Handle type="source" position={Position.Bottom} className="!h-1.5 !w-1.5" />
    </button>
  );
}

const nodeTypes = { agent: AgentNode };

const EDGE_TONE: Record<string, string> = {
  PASS: '#3ecf8e', 'FAIL / retry': '#f5a623', borderline: '#a78bfa',
  'retries exhausted': '#f2555a', 're-evaluate': '#f5a623',
};

export function WorkflowGraph({
  nodes, edges, stats, activeNode, selected, onSelect, height = 720,
}: {
  nodes: GraphNode[]; edges: GraphEdge[];
  stats?: Record<string, NodeStats>;
  activeNode?: string | null; selected?: string | null;
  onSelect?: (id: string) => void; height?: number;
}) {
  const flowNodes: Node<AgentNodeData>[] = useMemo(
    () => nodes.map((n) => ({
      id: n.id,
      type: 'agent',
      position: LAYOUT[n.id] ?? { x: 340, y: 0 },
      data: {
        label: n.label, description: n.description, stats: stats?.[n.id],
        active: activeNode === n.id, selected: selected === n.id,
        onSelect, nodeId: n.id,
      },
      draggable: true,
    })),
    [nodes, stats, activeNode, selected, onSelect],
  );

  const flowEdges: Edge[] = useMemo(
    () => edges.map((e, i) => {
      const color = EDGE_TONE[e.label] || '#2c3648';
      const animated = activeNode === e.source;
      return {
        id: `${e.source}-${e.target}-${i}`,
        source: e.source, target: e.target, label: e.label || undefined,
        type: 'smoothstep', animated,
        style: { stroke: color, strokeWidth: e.label ? 1.6 : 1.2 },
        labelStyle: { fill: color, fontSize: 9, fontFamily: 'var(--font-mono)' },
        labelBgStyle: { fill: '#0b0e14', fillOpacity: 0.9 },
        markerEnd: { type: MarkerType.ArrowClosed, color, width: 14, height: 14 },
      };
    }),
    [edges, activeNode],
  );

  const onInit = useCallback<OnInit>((inst) => {
    inst.fitView({ padding: 0.12 });
  }, []);

  return (
    <div style={{ height }} className="rounded-lg border border-line bg-base-950/60">
      <ReactFlow
        nodes={flowNodes} edges={flowEdges} nodeTypes={nodeTypes}
        onInit={onInit} fitView proOptions={{ hideAttribution: true }}
        minZoom={0.35} maxZoom={1.6} nodesConnectable={false} elementsSelectable
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1b2230" />
        <Controls className="!border-line !bg-base-900 [&_button]:!border-line [&_button]:!bg-base-850 [&_button]:!fill-slate-400" />
      </ReactFlow>
    </div>
  );
}
