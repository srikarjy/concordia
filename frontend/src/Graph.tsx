import { useEffect, useRef, useState } from 'react';
import Graph from 'graphology';
import Sigma from 'sigma';
import type { Edge, GraphNode } from './types';

const colors: Record<string, string> = {
  sequence: '#3de0b5', model: '#72a4cc', counterfactual: '#a68bd4',
  annotation: '#e2b660', claim: '#62d9b8', verification: '#ed7f74',
};

export function EvidenceGraph({ nodes, edges, selected, onSelect }: {
  nodes: GraphNode[]; edges: Edge[]; selected: Set<string>; onSelect: (id: string) => void;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [fallback, setFallback] = useState(false);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;
  useEffect(() => {
    if (!host.current) return;
    const worker = new Worker(new URL('./layout.worker.ts', import.meta.url), { type: 'module' });
    let renderer: Sigma | undefined;
    worker.onmessage = ({ data }: MessageEvent<{ id: string; x: number; y: number }[]>) => {
      if (!host.current) return;
      const graph = new Graph({ multi: true, type: 'directed' });
      for (const node of nodes) {
        const position = data.find(value => value.id === node.id)!;
        graph.addNode(node.id, { ...position, label: node.label,
          size: selected.has(node.id) ? 11 : 7,
          color: selected.size && !selected.has(node.id) ? '#2b403a' : colors[node.kind],
          forceLabel: selected.has(node.id), zIndex: selected.has(node.id) ? 2 : 0 });
      }
      edges.forEach((edge, index) => {
        if (graph.hasNode(edge.source) && graph.hasNode(edge.target))
          graph.addDirectedEdgeWithKey(String(index), edge.source, edge.target, {
            color: selected.has(edge.source) && selected.has(edge.target) ? '#3de0b5' : '#263b35',
            size: 1.5, type: 'arrow',
          });
      });
      try {
        renderer = new Sigma(graph, host.current, { renderLabels: true, labelSize: 12,
          labelColor: { color: '#a8bcb6' }, defaultEdgeType: 'arrow',
          stagePadding: 42, zIndex: true, allowInvalidContainer: true });
        renderer.on('clickNode', ({ node }) => selectRef.current(node));
      } catch { setFallback(true); }
    };
    worker.postMessage(nodes);
    return () => { worker.terminate(); renderer?.kill(); };
  }, [nodes, edges, selected]);
  return <>
    <div className="graph-canvas" ref={host} aria-label="Evidence provenance graph" />
    {fallback && <p className="muted">WebGL unavailable. Use the node controls below to inspect evidence.</p>}
    <div className="graph-node-list" aria-label="Accessible graph nodes">
      {nodes.map(node => <button key={node.id} className={selected.has(node.id) ? 'node active' : 'node'}
        onClick={() => onSelect(node.id)}>{node.label}</button>)}
    </div>
  </>;
}
