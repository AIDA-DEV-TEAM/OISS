"""Collect every district label from every source into harvested_names.csv (input for build_district_master.py).
Edit PATHS below to match where the files sit on your machine. Requires: pandas, openpyxl, and poppler's `pdftotext` on PATH."""
import re, subprocess, collections
from pathlib import Path
import pandas as pd, openpyxl

ROOT = Path(__file__).resolve().parent.parent          # repo root (scripts/ lives one level below)
RAW, EXT = ROOT / 'data' / 'raw', ROOT / 'data' / 'extracted'
PATHS = {
    'price_extract':      EXT / 'price_statistics_odisha_2020_raw_long.csv',
    'dag':                RAW / 'reference' / 'DAG_2026.xlsx',
    'oes':                RAW / 'reference' / 'OES_2026.xlsx',
    'earas_2022_23':      RAW / 'earas' / '2022-23',
    'earas_2023_24':      RAW / 'earas' / '2023-24',
    'earas_2024_25_crop': EXT / 'earas_2024_25_district_crop_ayp_raw.csv',
    'earas_2024_25_lu':   EXT / 'earas_2024_25_district_land_use_raw.csv',
    'report_2022_23':     RAW / 'earas' / '2022-23' / 'Technical_Report_on_EARAS__22_23.pdf',
    'report_2023_24':     RAW / 'earas' / '2023-24' / 'Technical_Report_on_EARAS_2023-24_Odisha.pdf',
}

seen = collections.defaultdict(collections.Counter)
def add(src, names):
    for n in names:
        if isinstance(n, str) and n.strip(): seen[n][src] += 1

def main():
    missing = [f'{k}: {p}' for k, p in PATHS.items() if not p.exists()]
    if missing: raise SystemExit('Missing inputs (fix PATHS):\n  ' + '\n  '.join(missing))

    add('price_stats_2020_pdf', pd.read_csv(PATHS['price_extract']).district_as_published)
    ws = openpyxl.load_workbook(PATHS['dag'], read_only=True, data_only=True).active
    add('district_at_a_glance_2026', [r[2] for r in list(ws.iter_rows(values_only=True))[6:]])
    wb = openpyxl.load_workbook(PATHS['oes'], read_only=True, data_only=True)
    for s in wb.worksheets:
        rows = list(s.iter_rows(values_only=True)); col = None
        for i, r in enumerate(rows[:8]):
            for j, c in enumerate(r):
                if isinstance(c, str) and re.fullmatch(r'\s*districts?\s*', c, re.I): col = (i, j)
        if col: add(f'OES_2026:{s.title.strip()}', [r[col[1]] for r in rows[col[0]+1:] if len(r) > col[1]])
    for f in sorted(PATHS['earas_2022_23'].glob('*.dta')):
        add(f'earas_2022_23:{f.stem}', pd.read_stata(f)['District'])
    for f in sorted(PATHS['earas_2023_24'].glob('*.csv')):
        add(f'earas_2023_24:{f.stem}', pd.read_csv(f, encoding='utf-8-sig')['District'])
    add('earas_report_2024_25:tables_5.x', pd.read_csv(PATHS['earas_2024_25_crop']).district_as_published)
    add('earas_report_2024_25:table_1.1', pd.read_csv(PATHS['earas_2024_25_lu']).district_as_published)
    for tag in ['report_2022_23', 'report_2023_24']:
        txt = subprocess.run(['pdftotext', '-layout', str(PATHS[tag]), '-'], capture_output=True, text=True, check=True).stdout
        for page in txt.split('\f'):
            if not re.search(r'District\s*-?\s*wise', page, re.I) or re.search(r'Block\s*-?\s*wise', page, re.I): continue
            for line in page.splitlines():
                m = re.match(r'^\s*(\d{1,2})\s+([A-Za-z][A-Za-z.\s]*?[A-Za-z.])\s{2,}[-\d.]', line)
                if m and 1 <= int(m.group(1)) <= 30:
                    add(f'earas_{tag}:district_tables', [re.sub(r'\s+S$', '', m.group(2).strip())])
    out = pd.DataFrame([dict(name_as_published=n, n_sources=len(c), sources='; '.join(sorted(c)), occurrences=sum(c.values()))
                        for n, c in seen.items()]).sort_values('name_as_published')
    out.to_csv(EXT / 'harvested_names.csv', index=False)
    print(f'{len(out)} distinct labels -> {EXT / "harvested_names.csv"}')

if __name__ == '__main__':
    main()
