import { useEffect, useRef, useState } from 'react';
import { createPluginUI } from 'molstar/lib/mol-plugin-ui/index.js';
import type { PluginUIContext } from 'molstar/lib/mol-plugin-ui/context.js';
import { renderReact18 } from 'molstar/lib/mol-plugin-ui/react18.js';
import { DefaultPluginUISpec } from 'molstar/lib/mol-plugin-ui/spec.js';
import { PluginConfig } from 'molstar/lib/mol-plugin/config.js';
import { Script } from 'molstar/lib/mol-script/script.js';
import { StructureSelection } from 'molstar/lib/mol-model/structure.js';
import { EmptyLoci } from 'molstar/lib/mol-model/loci.js';
import { Color } from 'molstar/lib/mol-util/color/index.js';
import { setStructureOverpaint } from 'molstar/lib/mol-plugin-state/helpers/structure-overpaint.js';
import 'molstar/lib/mol-plugin-ui/skin/light.scss';

export type MolstarViewerProps = {
  protectedPositions: number[]; buriedPositions: number[]; selected: number | null;
  structureText?: string; structureFormat?: string; structureLabel?: string;
};

export function MolstarViewer({ protectedPositions, buriedPositions, selected, structureText, structureFormat = 'pdb', structureLabel = '1IGV AlphaFold model' }: MolstarViewerProps) {
  const target = useRef<HTMLDivElement>(null);
  const active = useRef<PluginUIContext | null>(null);
  const [ready, setReady] = useState(false);
  const [status, setStatus] = useState('Loading AlphaFold structure…');
  useEffect(() => {
    let disposed = false;
    let instance: PluginUIContext | null = null;
    setReady(false);
    setStatus(`Loading ${structureLabel}…`);
    void (async () => {
      if (!target.current) return;
      if (!['pdb', 'cif', 'mmcif'].includes(structureFormat.toLowerCase())) throw new Error('Unsupported structure format');
      const spec = DefaultPluginUISpec();
      spec.layout = { initial: { isExpanded: false, showControls: false } };
      spec.components = { ...spec.components, remoteState: 'none', controls: { top: 'none', bottom: 'none', left: 'none', right: 'none' } };
      spec.config = [
        [PluginConfig.State.DefaultServer, ''],
        [PluginConfig.State.CurrentServer, ''],
        [PluginConfig.VolumeStreaming.Enabled, false],
      ];
      const plugin = await createPluginUI({ target: target.current, render: renderReact18, spec });
      instance = plugin;
      if (disposed) { plugin.dispose(); return; }
      active.current = plugin;
      const pdb = structureText ?? await fetch('/data/structure/1IGV.pdb').then((response) => {
        if (!response.ok) throw new Error('Structure file unavailable');
        return response.text();
      });
      if (disposed) return;
      if (typeof pdb !== 'string' || !pdb.trim()) throw new Error('Empty structure');
      const data = await plugin.builders.data.rawData({ data: pdb, label: structureLabel });
      const trajectory = await plugin.builders.structure.parseTrajectory(data, structureFormat.toLowerCase() === 'pdb' ? 'pdb' : 'mmcif');
      const model = await plugin.builders.structure.createModel(trajectory);
      const structure = await plugin.builders.structure.createStructure(model);
      if (structure) {
        const polymer = await plugin.builders.structure.tryCreateComponentStatic(structure, 'polymer');
        if (polymer) await plugin.builders.structure.representation.addRepresentation(polymer, { type: 'cartoon', color: 'uniform', colorParams: { value: Color(0xBBBBBB) } });
      }
      if (!disposed) { setReady(true); setStatus('Loaded · neutral coloring; pLDDT coloring off'); }
    })().catch(() => { if (!disposed) setStatus('Structure viewer failed to load'); });
    return () => { disposed = true; instance?.dispose(); if (active.current === instance) active.current = null; };
  }, [structureText, structureFormat, structureLabel]);
  const protectedKey = protectedPositions.join(',');
  const buriedKey = buriedPositions.join(',');
  useEffect(() => {
    const plugin = active.current;
    const current = plugin?.managers.structure.hierarchy.current.structures[0]?.cell.obj?.data;
    if (!ready || !plugin || !current) return;
    const residueLoci = (ids: number[]) => {
      const selection = Script.getStructureSelection((Q) => Q.struct.generator.atomGroups({
        'chain-test': Q.core.rel.eq([Q.struct.atomProperty.macromolecular.auth_asym_id(), 'A']),
        'residue-test': Q.core.set.has([Q.set(...ids), Q.struct.atomProperty.macromolecular.auth_seq_id()]),
      }), current);
      return StructureSelection.toLociWithSourceUnits(selection);
    };
    const components = plugin.managers.structure.hierarchy.current.structures[0]?.components ?? [];
    void (async () => {
      if (buriedKey) await setStructureOverpaint(plugin, components, Color(0x66CCEE), async () => residueLoci(buriedKey.split(',').map(Number)) ?? EmptyLoci);
      if (protectedKey) await setStructureOverpaint(plugin, components, Color(0xAA3377), async () => residueLoci(protectedKey.split(',').map(Number)) ?? EmptyLoci);
      plugin.managers.interactivity.lociSelects.deselectAll();
      if (selected) { const loci = residueLoci([selected]); plugin.managers.interactivity.lociSelects.select({ loci }); plugin.managers.camera.focusLoci(loci); }
    })().catch(() => setStatus('Structure loaded; residue highlighting unavailable'));
  }, [ready, selected, protectedKey, buriedKey]);
  return <div className="viewer-wrap"><div className="viewer-status">{status}{selected ? ` · selected position ${selected}` : ''}</div><div ref={target} className="molstar" role="img" aria-label={`${structureLabel}; uniform-grey cartoon with categorical residue highlights`} /></div>;
}
