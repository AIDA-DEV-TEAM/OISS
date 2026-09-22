/**
 * The ingest screen's target selection.
 *
 * Regression cover for the reported bug: the price CSV was uploaded while the
 * target read `earas_2022_23_block_land_use`, because the default was "whatever
 * dataset sorted first" rather than anything about the file.
 */
import { describe, expect, it } from 'vitest';

import type { IngestSchema } from '@/api/client';
import { matchSchema, scoreSchema } from '@/lib/matchSchema';

const SCHEMAS: IngestSchema[] = [
  {
    dataset_name: 'earas_2022_23_block_land_use',
    source_type: 'stata',
    expected_columns: [
      'Year', 'District', 'Block', 'Code', 'Block_Urban_Dist_State_Total',
      'Land_Use_Category', 'Area_Hectare',
    ],
  },
  {
    dataset_name: 'price_statistics_2020',
    source_type: 'csv',
    expected_columns: [
      'table_no', 'pdf_page', 'price_type', 'commodity', 'sl_no',
      'district_as_published', 'year', 'raw_value', 'price_rs_per_quintal',
      'cell_status',
    ],
  },
  {
    dataset_name: 'earas_2023_24_district_paddy',
    source_type: 'csv',
    expected_columns: [
      'Year', 'District', 'Season', 'Crop_Paddy_Rice', 'Area_000ha',
      'Yield_rate_qtl_ha', 'Production_000MT',
    ],
  },
];

const PRICE_HEADER = [
  'table_no', 'pdf_page', 'price_type', 'commodity', 'sl_no',
  'district_as_published', 'year', 'raw_value', 'price_rs_per_quintal',
  'cell_status',
];

describe('upload target selection', () => {
  it('picks the dataset the file actually is, not the first in the list', () => {
    const match = matchSchema(PRICE_HEADER, SCHEMAS);
    expect(match?.schema.dataset_name).toBe('price_statistics_2020');
    expect(match?.missing).toEqual([]);
    expect(match?.unexpected).toEqual([]);
  });

  it('never silently picks the Stata-backed dataset for a price CSV', () => {
    const match = matchSchema(PRICE_HEADER, SCHEMAS);
    expect(match?.schema.dataset_name).not.toBe('earas_2022_23_block_land_use');
    expect(match?.schema.source_type).toBe('csv');
  });

  it('chooses nothing when the file matches no declared schema', () => {
    const match = matchSchema(['alpha', 'beta', 'gamma'], SCHEMAS);
    // Null means the panel asks rather than guessing, and the upload that
    // follows reports SCHEMA_MISMATCH against whatever the user picks.
    expect(match).toBeNull();
  });

  it('reports which columns are missing and which are unexpected', () => {
    const partial = PRICE_HEADER.slice(0, 8).concat('surprise_column');
    const scored = scoreSchema(partial, SCHEMAS[1]);
    expect(scored.missing).toEqual(['price_rs_per_quintal', 'cell_status']);
    expect(scored.unexpected).toEqual(['surprise_column']);
  });

  it('tolerates the stray header whitespace the publisher ships', () => {
    const match = matchSchema(
      ['Year', 'District', 'Season ', 'Crop_Paddy_Rice', 'Area_000ha',
       'Yield_rate_qtl_ha', 'Production_000MT'],
      SCHEMAS,
    );
    expect(match?.schema.dataset_name).toBe('earas_2023_24_district_paddy');
  });

  it('returns nothing when there is no header to go on', () => {
    expect(matchSchema([], SCHEMAS)).toBeNull();
  });
});
