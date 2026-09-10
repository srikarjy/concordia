// Layout runs away from the interaction thread; all nodes arrive from saved evidence.
self.onmessage = ({ data }: MessageEvent<{ id: string; layer: number }[]>) => {
  const layers = new Map<number, number>();
  const counts = new Map<number, number>();
  for (const node of data) counts.set(node.layer, (counts.get(node.layer) ?? 0) + 1);
  self.postMessage(data.map(node => {
    const index = layers.get(node.layer) ?? 0;
    layers.set(node.layer, index + 1);
    return { id: node.id, x: node.layer * 2.3, y: index - ((counts.get(node.layer) ?? 1) - 1) / 2 };
  }));
};
