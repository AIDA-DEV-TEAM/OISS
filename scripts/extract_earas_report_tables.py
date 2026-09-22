"""Extract tables from DE&S Odisha 'Technical Report on EARAS' PDFs into long-format raw CSVs.

Outputs (values, names and units kept as published; no cleaning):
  earas_2024_25_district_crop_ayp_raw.csv   Tables 5.1-5.14 (2024-25 report): district x season x crop
  earas_2024_25_district_land_use_raw.csv   Table 1.1 (2024-25 report): district nine-fold land use
  earas_state_series_raw_all_reports.csv    Tables 20.1-20.14 from every report supplied, one row per report
  earas_state_series_latest.csv             Same series, keeping the value from the newest report per crop-year
  earas_state_series_revisions.csv          Values that changed between reports (numeric changes only)

Usage: python extract_earas_report_tables.py <report_2022_23.pdf> <report_2023_24.pdf> <report_2024_25.pdf>
(pdftotext from poppler must be on PATH.)
"""
import re, sys, csv, subprocess
from collections import defaultdict

REPORTS = sys.argv[1:] or ['Technical_Report_on_EARAS__22_23.pdf',
                           'Technical_Report_on_EARAS_2023-24_Odisha.pdf',
                           'Technical_Report_EARAS_2024-25_Odisha.pdf']
SEASONS = ['Autumn', 'Winter', 'Summer', 'Total']
TOKEN = r'(?:-?\d+(?:\.\d+)?|-+|S)'
issues = []

def pages(pdf):
    txt = subprocess.run(['pdftotext', '-layout', pdf, '-'], capture_output=True, text=True, check=True).stdout
    return txt.split('\f')

def report_year(pdf_pages):
    m = re.search(r'Technical Report on EARAS[,\s\-–]*?(\d{4}-\d{2})', '\n'.join(pdf_pages[:40]))
    return m.group(1) if m else None

def parse(tok):
    """published token -> (numeric value or '', cell_status)"""
    if re.fullmatch(r'-+', tok): return '', 'dash'
    if tok == 'S': return '', 'below_half_unit'
    return tok, 'ok'

def data_rows(page, ntok):
    """rows like ' 12   Jagatsinghpur   0.32 25.42 ...' and the STATE row"""
    out = []
    for line in page.splitlines():
        m = re.match(rf'^\s*(?:(\d{{1,2}})\s+)?([A-Za-z][A-Za-z.\s]*?)\s+((?:{TOKEN}\s+)*{TOKEN})\s*$', line)
        if not m: continue
        sl, name, toks = m.group(1), m.group(2).strip(), m.group(3).split()
        if (sl is None and name.upper() != 'STATE') or len(toks) != ntok: continue
        out.append((int(sl) if sl else None, name, toks))
    return out

# ---------- A. 2024-25 district crop tables 5.1-5.14 ----------
def district_crop_tables(pdf):
    pp = pages(pdf); yr = report_year(pp); rows = []
    for pno, page in enumerate(pp, 1):
        m = re.search(r'Table No\. *- *5\.(\d+)\s*\n\s*District wise and Season wise Estimates.*?\((\w+)\)', page)
        if not m: continue
        tno, crop = f'5.{m.group(1)}', m.group(2)
        paddy = crop.lower() == 'paddy'
        recs = data_rows(page, 20 if paddy else 12)
        if len(recs) != 31: issues.append(f'{pdf}: Table {tno} {crop}: expected 31 rows (30 districts + STATE), got {len(recs)}')
        if paddy:   # Area, Yield(paddy,rice), Production(paddy,rice) per season; Total block ordered Area, Y(p), Y(r), P(p), P(r)
            layout = [(s, meas, prod, unit) for s in SEASONS for meas, prod, unit in
                      [('area','paddy',"'000 ha"),('yield_rate','paddy','qtl/ha'),('yield_rate','rice','qtl/ha'),
                       ('production','paddy',"'000 MT"),('production','rice',"'000 MT")]]
        else:
            layout = [(s, meas, crop.lower(), unit) for s in SEASONS for meas, unit in
                      [('area','ha'),('yield_rate','qtl/ha'),('production','qtl')]]
        for sl, name, toks in recs:
            for (season, meas, product, unit), tok in zip(layout, toks):
                v, st = parse(tok)
                rows.append(dict(reference_year=yr, source_report=pdf, pdf_page=pno, table_no=tno, crop_table=crop,
                    product=product, sl_no=sl or '', district_as_published=name, is_state_total=int(sl is None),
                    season=season, measure=meas, unit=unit, raw_value=tok, value=v, cell_status=st))
    return rows

# ---------- B. 2024-25 Table 1.1 district land use ----------
LU = ['Forest','Land put to non-agricultural uses','Barren and un-cultivable land','Permanent pastures and other grazing land',
      'Land under misc. tree crops & groves not included in net area sown','Cultivable waste','Old fallows','Current fallows','Net area sown']
def land_use_table(pdf):
    pp = pages(pdf); yr = report_year(pp); rows = []
    for pno, page in enumerate(pp, 1):
        if not re.search(r'Table No\. *-\s*1\.1\s*\n\s*District wise Estimates of Area under Different Classification of Land Uses', page): continue
        recs = data_rows(page, 22)
        if len(recs) != 31: issues.append(f'{pdf}: Table 1.1: expected 31 rows, got {len(recs)}')
        layout = [(c, m, u) for c in LU for m, u in [('area',"'000 ha"),('pct_of_area_under_survey','%')]] + \
                 [('Total area under survey','area',"'000 ha"),('Total area under survey','pct_of_geographical_area','%'),
                  ('Area not included under survey','area',"'000 ha"),('Geographical area','area',"'000 ha")]
        for sl, name, toks in recs:
            for (cat, meas, unit), tok in zip(layout, toks):
                v, st = parse(tok)
                rows.append(dict(reference_year=yr, source_report=pdf, pdf_page=pno, table_no='1.1', sl_no=sl or '',
                    district_as_published=name, is_state_total=int(sl is None), land_use_category=cat,
                    measure=meas, unit=unit, raw_value=tok, value=v, cell_status=st))
    return rows

# ---------- C. State series 20.1-20.14, all reports ----------
def state_series(pdf):
    pp = pages(pdf); yr = report_year(pp); rows = []
    for pno, page in enumerate(pp, 1):
        m = re.search(r'Table No\. *- *20\.(\d+)\s*\n', page)
        if not m: continue
        c = re.search(r'to \d{4}-\d{2}\)\s*-\s*(\w+)', page) or re.search(r'CROP *: *(\w+)', page)
        if not c: continue
        crop = c.group(1).capitalize(); paddy = crop == 'Paddy'
        if paddy:
            layout = [(s,'area','paddy',"'000 ha") for s in SEASONS] + [(s,'yield_rate','paddy','qtl/ha') for s in SEASONS] + \
                     [(s,'yield_rate','rice','qtl/ha') for s in SEASONS] + [(s,'production','paddy',"'000 MT") for s in SEASONS] + \
                     [(s,'production','rice',"'000 MT") for s in SEASONS]
        else:
            layout = [(s,'area',crop.lower(),'ha') for s in SEASONS] + [(s,'yield_rate',crop.lower(),'qtl/ha') for s in SEASONS] + \
                     [(s,'production',crop.lower(),'qtl') for s in SEASONS]
        n = 0
        for line in page.splitlines():
            mm = re.match(rf'^\s*\d+\s+(\d{{4}}-\d{{2}})\s+((?:{TOKEN}\s+)*{TOKEN})\s*$', line)
            if not mm: continue
            toks = mm.group(2).split()
            if len(toks) != len(layout): issues.append(f'{pdf}: Table 20.{m.group(1)} {crop} {mm.group(1)}: {len(toks)} values'); continue
            n += 1
            for (season, meas, product, unit), tok in zip(layout, toks):
                v, st = parse(tok)
                rows.append(dict(reference_year=mm.group(1), crop=crop, product=product, season=season, measure=meas, unit=unit,
                    raw_value=tok, value=v, cell_status=st, source_report=pdf, report_year=yr, table_no=f'20.{m.group(1)}', pdf_page=pno))
        if n != 30: issues.append(f'{pdf}: Table 20.{m.group(1)} {crop}: {n} year rows')
    return rows

def write(path, rows):
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)

if __name__ == '__main__':
    latest = REPORTS[-1]
    A = district_crop_tables(latest); write('earas_2024_25_district_crop_ayp_raw.csv', A)
    B = land_use_table(latest);      write('earas_2024_25_district_land_use_raw.csv', B)
    C = [r for pdf in REPORTS for r in state_series(pdf)]; write('earas_state_series_raw_all_reports.csv', C)
    key = lambda r: (r['crop'], r['product'], r['reference_year'], r['season'], r['measure'])
    by = defaultdict(list)
    for r in C: by[key(r)].append(r)
    L, R = [], []
    for k, rs in sorted(by.items()):
        rs.sort(key=lambda r: r['report_year'])
        new = dict(rs[-1]); new['reports_containing_value'] = len(rs); L.append(new)
        for a, b in zip(rs, rs[1:]):
            if a['value'] != b['value'] and not (a['value'] and b['value'] and float(a['value']) == float(b['value'])):
                R.append(dict(crop=k[0], product=k[1], reference_year=k[2], season=k[3], measure=k[4], unit=a['unit'],
                              old_value=a['raw_value'], old_report_year=a['report_year'], new_value=b['raw_value'], new_report_year=b['report_year']))
    write('earas_state_series_latest.csv', L)
    if R: write('earas_state_series_revisions.csv', R)
    print(f'A district crop rows: {len(A)} | B land use rows: {len(B)} | C series rows (all reports): {len(C)} | latest: {len(L)} | revisions: {len(R)}')
    for i in issues: print('ISSUE:', i)
