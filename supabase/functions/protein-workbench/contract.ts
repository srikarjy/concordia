export const SETTINGS_VERSION = 'query-only-v1';
export const SCOPE = 'Computational predictions only. Structure confidence and agreement do not establish folding stability, expression, binding or function. Uploaded proteins do not receive the frozen 1IGV stability scores.';
export function parseProtein(value: unknown): string {
  if (typeof value !== 'string' || new TextEncoder().encode(value).length > 8192) throw new Error('Use a sequence or single-record FASTA of at most 8 KB.');
  const lines = value.trim().split(/\r?\n/);
  if (lines[0]?.startsWith('>')) lines.shift();
  if (lines.some((line) => line.includes('>'))) throw new Error('Upload exactly one protein sequence.');
  const seq = lines.join('').replace(/\s/g, '').toUpperCase();
  if (!/^[ACDEFGHIKLMNPQRSTVWY]{20,300}$/.test(seq)) throw new Error('Use 20–300 residues from the twenty standard amino acids; no gaps, stops or ambiguous letters.');
  return seq;
}
export function parsedStructure(model: string, body: unknown) {
  const value = body as { structures?: Array<{ structure?: string; format?: string }>; outputs?: Array<{ structures_with_scores?: Array<{ structure?: string; format?: string }> }> } | null;
  const first = model === 'boltz2' ? value?.structures?.[0] : value?.outputs?.[0]?.structures_with_scores?.[0];
  if (!first || typeof first.structure !== 'string' || !['pdb', 'cif', 'mmcif'].includes(first.format ?? '')) throw new Error('Unsupported provider response');
  if (!/(^ATOM |^HETATM |^data_)/m.test(first.structure)) throw new Error('Structure records missing');
  return { structure_text: first.structure, structure_format: first.format };
}
