import assert from 'node:assert/strict';
import test from 'node:test';
import { parseProtein, parsedStructure } from '../functions/protein-workbench/contract.ts';
const sequence = 'SPEELKGIFEKYAAKEGDPNQLSKEELKLLLQTEFPSLLKGPSTLDELFEELDKNGDGEVSFEEFQVLVKKISQ';
test('FASTA normalization preserves sequence and rejects extra records', () => {
  assert.equal(parseProtein(`>1IGV\n${sequence.toLowerCase()}\n`), sequence);
  assert.throws(() => parseProtein(`>one\n${sequence}\n>two\n${sequence}`));
});
test('invalid alphabet, short, large and non-string inputs fail before provider access', () => {
  for (const input of [null, {}, 'A', 'A'.repeat(301), sequence + '*', sequence + 'X', 'A'.repeat(8193)]) assert.throws(() => parseProtein(input));
});
test('OpenFold3 response uses outputs structures_with_scores', () => {
  assert.deepEqual(parsedStructure('openfold3', { outputs: [{ structures_with_scores: [{ format: 'cif', structure: 'data_test\n_atom_site.id' }] }] }), { structure_format: 'cif', structure_text: 'data_test\n_atom_site.id' });
  assert.throws(() => parsedStructure('openfold3', { outputs: [] }));
  assert.throws(() => parsedStructure('boltz2', { structures: [{ format: 'pdb', structure: 'not a structure' }] }));
});
