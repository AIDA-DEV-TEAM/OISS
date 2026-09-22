"""Generate a representative MONTHLY district price dataset for the OISS PoC.

The series are SYNTHETIC. They are modelled on the real DE&S publication
"Price Statistics of Odisha 2020 (Provisional)" (district averages, 2013-14 to 2018-19) and must never be
presented as DE&S price statistics. Every output row carries data_origin='synthetic' plus the basis used
for its annual level, so the flag can be propagated into KPIs, charts, model inputs and exports.

Method
  1. Annual level per (district, price type, commodity, agricultural year):
       - published        the real published district average for that year
       - imputed          crop-year state level x that district's average ratio to the state (years the
                          publication printed "-" for a district that does have data in other years)
       - projected        2019-20 onward: last published year grown at the crop's own 2013-19 CAGR,
                          clipped to PROJECTION_GROWTH_BOUNDS
     Series with no published value at all are skipped, so no market is invented where the crop is not priced.
  2. Monthly shape: a harvest-centred seasonal curve (trough at harvest, peak in the lean months) plus
     AR(1) noise from a seeded generator, then rescaled so the months of a year average exactly to the
     annual level above. Farm harvest prices exist only in the harvest window (the concept is defined at
     harvest); wholesale prices run all 12 months.
  3. Agricultural year = July to June, matching EARAS.

Reads data/extracted/ and writes data/synthetic/, both located relative to this script (repo root = its parent).
Usage: python scripts/generate_synthetic_prices.py   [optional: price_extract.csv district_master.csv district_aliases.csv out_dir]
"""
import sys, hashlib, math, re
from pathlib import Path
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parent.parent          # repo root (scripts/ lives one level below)
EXTRACTED, SYNTHETIC = ROOT / 'data' / 'extracted', ROOT / 'data' / 'synthetic'

GENERATOR_VERSION = 'synthetic-prices-v1'
SEED = 20260917
YEARS = [f'{y}-{str(y+1)[2:]}' for y in range(2013, 2025)]        # 2013-14 .. 2024-25
LAST_PUBLISHED_YEAR = '2018-19'
PROJECTION_GROWTH_BOUNDS = (0.01, 0.10)                            # annual, clipped
DEFAULT_GROWTH = 0.05
SEASONAL_AMPLITUDE = {'Farm Harvest': 0.03, 'Wholesale': 0.08}     # fraction around the annual mean
NOISE_SD = {'Farm Harvest': 0.015, 'Wholesale': 0.025}
AR1 = 0.6
# calendar month in which the crop is harvested in Odisha (trough of the price curve)
HARVEST_MONTH = {'Paddy':12,'Wheat':3,'Maize':10,'Ragi':11,'Mung':3,'Biri':3,'Kulthi':2,'Til':3,'Groundnut':3,
                 'Mustard':2,'Jute':8,'Potato':2,'Sugarcane':2,'Jowar':11,'Bajra':10,'Gram':3,'Arhar':2,
                 'Castor':2,'Sunflower':3,'Linseed':3,'Onion':4,'Cotton':12}
HARVEST_WINDOW = 3                                                 # months of farm-harvest price per year

def agri_months(year):
    """(calendar_year, month) for July..June of an agricultural year label like '2016-17'."""
    y0 = int(year[:4])
    return [(y0, m) for m in range(7, 13)] + [(y0 + 1, m) for m in range(1, 7)]

def main(price_csv, master_csv, alias_csv, out_dir):
    missing = [str(p) for p in (price_csv, master_csv, alias_csv) if not Path(p).exists()]
    if missing: raise SystemExit('Missing input(s):\n  ' + '\n  '.join(missing))
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    px = pd.read_csv(price_csv)
    master = pd.read_csv(master_csv)
    alias = pd.read_csv(alias_csv)
    lookup = dict(zip(alias.normalised_key, alias.district_id))
    name = dict(zip(master.district_id, master.display_name))
    px['district_id'] = px.district_as_published.map(lambda s: lookup.get(re.sub(r'[^A-Z]', '', str(s).upper())))
    assert px.district_id.notna().all(), 'unmapped district in the price extract'
    px = px[px.cell_status.isin(['ok', 'provisional'])].copy()
    px['value'] = px.price_rs_per_quintal.astype(float)

    # crop/state level per year, for imputation and projection
    state = px.groupby(['price_type', 'commodity', 'year']).value.mean()
    rows, audit = [], []
    keys = sorted(px.groupby(['price_type', 'commodity', 'district_id']).groups)
    for price_type, commodity, did in keys:
        g = px[(px.price_type == price_type) & (px.commodity == commodity) & (px.district_id == did)]
        published = dict(zip(g.year, g.value))
        if not published: continue
        ratios = [published[y] / state[(price_type, commodity, y)] for y in published if state.get((price_type, commodity, y))]
        ratio = float(np.mean(ratios)) if ratios else 1.0
        # crop growth rate from the state series
        s = state[(price_type, commodity)].reindex(YEARS[:6]).dropna()
        growth = (s.iloc[-1] / s.iloc[0]) ** (1 / (len(s) - 1)) - 1 if len(s) > 1 else DEFAULT_GROWTH
        growth = float(np.clip(growth, *PROJECTION_GROWTH_BOUNDS))
        last_level = published.get(LAST_PUBLISHED_YEAR) or (ratio * state[(price_type, commodity, max(published))])

        # deterministic per-series stream (stable across runs and machines: hashlib, not Python's salted hash())
        digest = hashlib.md5(f'{GENERATOR_VERSION}|{SEED}|{price_type}|{commodity}|{did}'.encode()).digest()
        rng = np.random.default_rng(int.from_bytes(digest[:8], 'big'))
        eps = 0.0
        for year in YEARS:
            if year in published:
                level, basis = published[year], 'published'
            elif year <= LAST_PUBLISHED_YEAR:
                st = state.get((price_type, commodity, year))
                if st is None or math.isnan(st): continue
                level, basis = ratio * st, 'imputed'
            else:
                k = YEARS.index(year) - YEARS.index(LAST_PUBLISHED_YEAR)
                level, basis = last_level * (1 + growth) ** k, 'projected'
            hm = HARVEST_MONTH.get(commodity, 3)
            months = agri_months(year)
            if price_type == 'Farm Harvest':
                months = [m for m in months if min((m[1] - hm) % 12, (hm - m[1]) % 12) < HARVEST_WINDOW / 2 + 0.5][:HARVEST_WINDOW]
            shaped = []
            for cal_y, m in months:
                phase = 2 * math.pi * ((m - hm) % 12) / 12
                seasonal = 1 - SEASONAL_AMPLITUDE[price_type] * math.cos(phase)
                eps = AR1 * eps + rng.normal(0, NOISE_SD[price_type])
                shaped.append((cal_y, m, seasonal * (1 + eps)))
            mean_shape = float(np.mean([s for _, _, s in shaped]))
            for cal_y, m, s in shaped:
                rows.append(dict(agri_year=year, month_start=f'{cal_y}-{m:02d}-01', calendar_year=cal_y, month=m,
                                 district_id=did, district=name[did], price_type=price_type, commodity=commodity,
                                 price_rs_per_quintal=round(level * s / mean_shape, 2), unit='Rs/quintal',
                                 data_origin='synthetic', annual_level_basis=basis,
                                 annual_level_rs_per_quintal=round(level, 2),
                                 generator_version=GENERATOR_VERSION, generator_seed=SEED))
            audit.append(dict(price_type=price_type, commodity=commodity, district_id=did, agri_year=year,
                              basis=basis, annual_level=round(level, 2), months=len(months)))
    out = pd.DataFrame(rows)
    out.to_csv(out_dir / 'synthetic_monthly_prices.csv', index=False)
    a = pd.DataFrame(audit); a.to_csv(out_dir / 'synthetic_prices_annual_levels.csv', index=False)

    # reconciliation: monthly mean must equal the annual level it was built from
    chk = out.groupby(['price_type', 'commodity', 'district_id', 'agri_year']).agg(
        monthly_mean=('price_rs_per_quintal', 'mean'), level=('annual_level_rs_per_quintal', 'first')).reset_index()
    chk['abs_diff'] = (chk.monthly_mean - chk.level).abs()
    chk.to_csv(out_dir / 'synthetic_prices_reconciliation.csv', index=False)
    print(f'rows: {len(out):,} | series: {len(keys):,} | years: {YEARS[0]}..{YEARS[-1]}')
    print(a.basis.value_counts().to_dict())
    print(f'reconciliation: max |monthly mean - annual level| = {chk.abs_diff.max():.4f} Rs '
          f'| cells off by >0.01 = {(chk.abs_diff > 0.01).sum()}')
    print(f'written to {out_dir}')

if __name__ == '__main__':
    defaults = [EXTRACTED / 'price_statistics_odisha_2020_raw_long.csv', EXTRACTED / 'district_master.csv',
                EXTRACTED / 'district_aliases.csv', SYNTHETIC]
    args = sys.argv[1:] or defaults
    main(*args)