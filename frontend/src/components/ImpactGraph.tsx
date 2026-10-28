"use client";

import { useMemo } from "react";
import { Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { GraphEdge, GraphNode, Risk } from "@/lib/types";
import { Empty, PanelHeader } from "./ui";

const COL_WIDTH = 250;
const ROW_HEIGHT = 86;

type NodeData = { node: GraphNode; highlighted: boolean };

function FnNode({ data }: { data: NodeData }) {
  const { node, highlighted } = data;
  const ring = highlighted
    ? "border-red-400 shadow-[0_0_0_3px_rgba(248,113,113,0.25)]"
    : node.changed
      ? "border-amber-400/70"
      : "border-white/10";
  return (
    <div className={`w-[210px] rounded-md border bg-[#141821] px-2.5 py-1.5 ${ring}`}>
      <Handle type="target" position={Position.Left} className="!h-1.5 !w-1.5 !border-0 !bg-slate-500" />
      <div className="flex items-center gap-1.5">
        <span
          className={`text-[9px] font-semibold uppercase tracking-wider ${
            node.kind === "route" ? "text-violet-300" : node.kind === "file" ? "text-sky-300" : "text-slate-500"
          }`}
        >
          {node.kind}
        </span>
        {node.changed && <span className="text-[9px] font-semibold uppercase tracking-wider text-amber-300">changed</span>}
      </div>
      <div className="truncate font-mono text-[12px] text-slate-100" title={node.label}>
        {node.label}
      </div>
      {node.route && <div className="truncate font-mono text-[10.5px] text-violet-300/80">{node.route}</div>}
      <div className="truncate font-mono text-[10px] text-slate-500" title={node.file}>
        {node.file}
        {node.line ? `:${node.line}` : ""}
      </div>
      <Handle type="source" position={Position.Right} className="!h-1.5 !w-1.5 !border-0 !bg-slate-500" />
    </div>
  );
}

const nodeTypes = { fn: FnNode };

/** Longest-path layering: callers on the left, callees on the right. */
function layout(nodes: GraphNode[], edges: GraphEdge[]): Map<string, { x: number; y: number }> {
  const layer = new Map<string, number>(nodes.map((n) => [n.id, 0]));
  for (let pass = 0; pass < nodes.length; pass++) {
    let changed = false;
    for (const e of edges) {
      const next = (layer.get(e.source) ?? 0) + 1;
      if (layer.has(e.target) && next > (layer.get(e.target) ?? 0) && next < nodes.length) {
        layer.set(e.target, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  const columns = new Map<number, GraphNode[]>();
  for (const n of nodes) {
    const l = layer.get(n.id) ?? 0;
    columns.set(l, [...(columns.get(l) ?? []), n]);
  }
  const positions = new Map<string, { x: number; y: number }>();
  const tallest = Math.max(...Array.from(columns.values()).map((c) => c.length));
  columns.forEach((col, l) => {
    col.sort((a, b) => Number(b.changed) - Number(a.changed) || a.file.localeCompare(b.file));
    const offset = ((tallest - col.length) * ROW_HEIGHT) / 2;
    col.forEach((n, i) => positions.set(n.id, { x: l * COL_WIDTH, y: offset + i * ROW_HEIGHT }));
  });
  return positions;
}

/** Nodes tied to the selected risk: its test target and the function enclosing its cited line. */
function highlightedIds(nodes: GraphNode[], risk: Risk | null): Set<string> {
  const ids = new Set<string>();
  if (!risk) return ids;
  for (const n of nodes) {
    if (risk.test_target && (n.route === risk.test_target || n.id === risk.test_target)) ids.add(n.id);
  }
  const inFile = nodes.filter((n) => n.kind !== "file" && n.file === risk.file && n.line != null);
  const enclosing = inFile
    .filter((n) => risk.line != null && (n.line ?? 0) <= risk.line)
    .sort((a, b) => (b.line ?? 0) - (a.line ?? 0))[0];
  if (enclosing) ids.add(enclosing.id);
  else if (ids.size === 0) inFile.filter((n) => n.changed).forEach((n) => ids.add(n.id));
  return ids;
}

export function ImpactGraph({
  nodes,
  edges,
  selectedRisk,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  selectedRisk: Risk | null;
}) {
  const { flowNodes, flowEdges } = useMemo(() => {
    const pos = layout(nodes, edges);
    const highlighted = highlightedIds(nodes, selectedRisk);
    const flowNodes: Node<NodeData>[] = nodes.map((n) => ({
      id: n.id,
      type: "fn",
      position: pos.get(n.id) ?? { x: 0, y: 0 },
      data: { node: n, highlighted: highlighted.has(n.id) },
    }));
    const flowEdges: Edge[] = edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.kind === "imports" ? "imports" : undefined,
      animated: e.confidence === "candidate",
      style: {
        stroke: e.kind === "imports" ? "#38bdf8" : e.confidence === "resolved" ? "#64748b" : "#a78bfa",
        strokeDasharray: e.confidence === "candidate" ? "4 3" : undefined,
        strokeWidth: 1.4,
      },
      labelStyle: { fill: "#94a3b8", fontSize: 10 },
      labelBgStyle: { fill: "#0b0d12" },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: "#64748b" },
    }));
    return { flowNodes, flowEdges };
  }, [nodes, edges, selectedRisk]);

  return (
    <section className="flex min-h-0 flex-col">
      <PanelHeader
        title="Impact graph"
        right={
          <div className="flex items-center gap-3 text-[10.5px] text-slate-500">
            <span className="flex items-center gap-1">
              <span className="h-2 w-2 rounded-sm border border-amber-400" /> changed
            </span>
            <span className="flex items-center gap-1">
              <span className="h-px w-4 bg-slate-500" /> resolved call
            </span>
            <span className="flex items-center gap-1">
              <span className="h-px w-4 border-t border-dashed border-violet-400" /> candidate
            </span>
          </div>
        }
      />
      <div className="relative min-h-0 flex-1">
        {nodes.length === 0 ? (
          <Empty>The graph of changed and connected code appears here.</Empty>
        ) : (
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            fitView
            fitViewOptions={{ padding: 0.2 }}
            nodesConnectable={false}
            proOptions={{ hideAttribution: true }}
            colorMode="dark"
            minZoom={0.3}
          >
            <Background color="#1e2430" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        )}
      </div>
      {edges.length > 0 && (
        <div className="scrollbar-thin max-h-28 shrink-0 overflow-auto border-t border-white/5 px-3 py-1.5">
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-500">Edge evidence</div>
          {edges.map((e) => (
            <div key={e.id} className="truncate font-mono text-[10.5px] text-slate-400" title={e.evidence}>
              <span className={e.confidence === "resolved" ? "text-slate-500" : "text-violet-300"}>[{e.confidence}]</span>{" "}
              {e.evidence}
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
