/**
 * Constants and reference values for the analytics dashboard.
 * Derived from DESIGN.md and DE&S master tables.
 */

/**
 * Okabe-Ito chart palette (DESIGN.md §2), by reference rather than by value.
 *
 * Recharts needs a colour string for `stroke` and `fill`, so it cannot take a
 * Tailwind class. Pointing at the custom properties keeps tokens.css the single
 * source of truth: the palette is defined once, and a change there reaches both
 * the Tailwind `chart.1`-`chart.8` utilities and every chart series.
 */
export const CHART_COLORS = [
  'var(--chart-1)', // Blue
  'var(--chart-2)', // Orange
  'var(--chart-3)', // Green
  'var(--chart-4)', // Pink/Mauve
  'var(--chart-5)', // Sky Blue
  'var(--chart-6)', // Vermilion
  'var(--chart-7)', // Ochre
  'var(--chart-8)', // Charcoal
];

/** Non-series colours charts need, also by reference (DESIGN.md §2 and §6). */
export const CHART_INK = {
  grid: 'var(--color-border)',
  axis: 'var(--color-text-subtle)',
  reference: 'var(--color-border-strong)',
  error: 'var(--color-error)',
  success: 'var(--color-success)',
} as const;

export const PADDY_CROP_ID = 'CR17';

/** The 13 crops published with both Farm Harvest and Wholesale prices */
export const DUAL_PRICE_CROPS = [
  { id: 'CR03', name: 'Biri' },
  { id: 'CR07', name: 'Groundnut' },
  { id: 'CR09', name: 'Jute' },
  { id: 'CR10', name: 'Kulthi' },
  { id: 'CR12', name: 'Maize' },
  { id: 'CR13', name: 'Mung' },
  { id: 'CR14', name: 'Mustard' },
  { id: 'CR17', name: 'Paddy' },
  { id: 'CR18', name: 'Potato' },
  { id: 'CR19', name: 'Ragi' },
  { id: 'CR20', name: 'Sugarcane' },
  { id: 'CR22', name: 'Til' },
  { id: 'CR23', name: 'Wheat' },
];

export const SEASONS = ['Autumn', 'Winter', 'Summer', 'Total'] as const;
export type Season = (typeof SEASONS)[number];

export const PRICE_TYPES = [
  { id: 'farm_harvest', label: 'Farm harvest' },
  { id: 'wholesale', label: 'Wholesale' },
] as const;

export const AGRI_YEARS = [
  '2013-14',
  '2014-15',
  '2015-16',
  '2016-17',
  '2017-18',
  '2018-19',
  '2019-20',
  '2020-21',
  '2021-22',
  '2022-23',
  '2023-24',
  '2024-25',
] as const;

export const ALL_DISTRICTS = [
  { id: 'OD01', name: 'Angul' },
  { id: 'OD02', name: 'Balangir' },
  { id: 'OD03', name: 'Balasore' },
  { id: 'OD04', name: 'Bargarh' },
  { id: 'OD05', name: 'Bhadrak' },
  { id: 'OD06', name: 'Boudh' },
  { id: 'OD07', name: 'Cuttack' },
  { id: 'OD08', name: 'Deogarh' },
  { id: 'OD09', name: 'Dhenkanal' },
  { id: 'OD10', name: 'Gajapati' },
  { id: 'OD11', name: 'Ganjam' },
  { id: 'OD12', name: 'Jagatsinghpur' },
  { id: 'OD13', name: 'Jajpur' },
  { id: 'OD14', name: 'Jharsuguda' },
  { id: 'OD15', name: 'Kalahandi' },
  { id: 'OD16', name: 'Kandhamal' },
  { id: 'OD17', name: 'Kendrapara' },
  { id: 'OD18', name: 'Keonjhar' },
  { id: 'OD19', name: 'Khordha' },
  { id: 'OD20', name: 'Koraput' },
  { id: 'OD21', name: 'Malkangiri' },
  { id: 'OD22', name: 'Mayurbhanj' },
  { id: 'OD23', name: 'Nabarangpur' },
  { id: 'OD24', name: 'Nayagarh' },
  { id: 'OD25', name: 'Nuapada' },
  { id: 'OD26', name: 'Puri' },
  { id: 'OD27', name: 'Rayagada' },
  { id: 'OD28', name: 'Sambalpur' },
  { id: 'OD29', name: 'Subarnapur' },
  { id: 'OD30', name: 'Sundargarh' },
];

export const ALL_CROPS = [
  { id: 'CR01', name: 'Arhar' },
  { id: 'CR02', name: 'Bajra' },
  { id: 'CR03', name: 'Biri' },
  { id: 'CR04', name: 'Castor' },
  { id: 'CR05', name: 'Cotton' },
  { id: 'CR06', name: 'Gram' },
  { id: 'CR07', name: 'Groundnut' },
  { id: 'CR08', name: 'Jowar' },
  { id: 'CR09', name: 'Jute' },
  { id: 'CR10', name: 'Kulthi' },
  { id: 'CR11', name: 'Linseed' },
  { id: 'CR12', name: 'Maize' },
  { id: 'CR13', name: 'Mung' },
  { id: 'CR14', name: 'Mustard' },
  { id: 'CR15', name: 'Nizer' },
  { id: 'CR16', name: 'Onion' },
  { id: 'CR17', name: 'Paddy' },
  { id: 'CR18', name: 'Potato' },
  { id: 'CR19', name: 'Ragi' },
  { id: 'CR20', name: 'Sugarcane' },
  { id: 'CR21', name: 'Sunflower' },
  { id: 'CR22', name: 'Til' },
  { id: 'CR23', name: 'Wheat' },
];

export const LAND_USE_CATEGORIES = [
  'Forests',
  'Barren and unculturable land',
  'Land put to non-agricultural uses',
  'Culturable waste',
  'Permanent pastures and other grazing land',
  'Land under miscellaneous tree crops and groves',
  'Current fallow',
  'Other fallow',
  'Net area sown',
] as const;
