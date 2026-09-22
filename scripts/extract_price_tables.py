"""Extract district-level price Tables 1-35 from DE&S Odisha 'Price Statistics of Odisha 2020 (Provisional)'
into a long-format raw CSV. Values are kept as published; cells are assigned to year columns by x-position.
Usage: python extract_price_tables.py price-statistics-odisha-2020.pdf
"""
import pdfplumber, re, csv, collections
import sys
PDF=sys.argv[1] if len(sys.argv)>1 else 'price-statistics-odisha-2020.pdf'
YEARS=['2013-14','2014-15','2015-16','2016-17','2017-18','2018-19']
rows=[]; report=[]
with pdfplumber.open(PDF) as pdf:
    for pno,page in enumerate(pdf.pages,1):
        txt=page.extract_text() or ''
        m=re.search(r'Table (\d+):\s*District Average (Farm Harvest|Wholesale) Prices of (\w+)',txt)
        if not m: continue
        tno=int(m.group(1)); ptype=m.group(2); crop=m.group(3)
        words=page.extract_words(keep_blank_chars=False, x_tolerance=1.5)
        hdr={w['text']:w for w in words if w['text'] in YEARS}
        if len(hdr)!=6: report.append((tno,'header years found',len(hdr))); continue
        centers=[(y,(hdr[y]['x0']+hdr[y]['x1'])/2) for y in YEARS]
        hdr_bottom=max(w['bottom'] for w in hdr.values())
        # group words into lines
        lines={}; cur=None; key=0
        for w in sorted([w for w in words if w['top']>hdr_bottom+2],key=lambda w:w['top']):
            if cur is None or w['top']-cur>6: key+=1; lines[key]=[]; cur=w['top']
            lines[key].append(w)
        n=0
        namecut=centers[0][1]-25
        orphans=[]  # name fragments on lines without a serial number (wrapped names)
        for k in sorted(lines):
            ws=sorted(lines[k],key=lambda w:w['x0'])
            if ws and not re.fullmatch(r'\d{1,2}',ws[0]['text']) and all(w['x1']<namecut for w in ws) and ws[0]['x0']>40:
                orphans.append((ws[0]['top'],' '.join(w['text'] for w in ws)))
        # re-join decimals wrapped onto the next line (e.g. '2786.428' + '6')
        keys=sorted(lines)
        for a,b in zip(keys,keys[1:]):
            frag=lines[b]
            if frag and all(re.fullmatch(r'\d+',w['text']) and w['x0']>namecut for w in frag) and len(frag)<=2:
                for fw in frag:
                    for vw in lines[a]:
                        if '.' in vw['text'] and abs(vw['x1']-fw['x1'])<4:
                            report.append((tno,'wrapped decimal joined',vw['text']+'+'+fw['text'])); vw['text']+=fw['text']; fw['text']='__used__'
                lines[b]=[w for w in frag if w['text']!='__used__']
        for k in sorted(lines):
            ws=sorted(lines[k],key=lambda w:w['x0'])
            if not ws or not re.fullmatch(r'\d{1,2}',ws[0]['text']): continue
            sl=int(ws[0]['text'])
            name=[w['text'] for w in ws[1:] if w['x1']<namecut]
            if not name:
                near=[o for o in orphans if abs(o[0]-ws[0]['top'])<14]
                if near:
                    name=[re.sub(r'(\w) (\w)$', r'\1\2', ' '.join(o[1] for o in sorted(near)))]; report.append((tno,'wrapped name joined',sl,name[0]))
            cells=[w for w in ws[1:] if w['x1']>=centers[0][1]-25]
            if not name or sl>30: continue
            vals={y:'' for y in YEARS}
            for w in cells:
                c=(w['x0']+w['x1'])/2
                y=min(centers,key=lambda t:abs(t[1]-c))
                if abs(y[1]-c)>40: report.append((tno,'unassigned',w['text'])); continue
                vals[y[0]]=(vals[y[0]]+' '+w['text']).strip()
            n+=1
            for y in YEARS:
                raw=vals[y]
                num=re.sub(r'[*,\s]','',raw)
                if raw=='': flag='blank'; v=''
                elif re.fullmatch(r'[-–—]+',num): flag='dash'; v=''
                elif re.fullmatch(r'\d+(\.\d+)?',num): flag='provisional' if '*' in raw else 'ok'; v=num
                else: flag='unparsed'; v=''
                rows.append(dict(table_no=tno,pdf_page=pno,price_type=ptype,commodity=crop,sl_no=sl,
                    district_as_published=' '.join(name),year=y,raw_value=raw,price_rs_per_quintal=v,cell_status=flag))
        report.append((tno,ptype,crop,'district rows',n))
# Undo PDF line-wrap artifacts in district names (extraction artifacts only; publisher spellings are kept as-is)
for r in rows:
    r['district_as_published']=re.sub(r'^(Nabarangapu|Jagatsinghpu)( r)?$',r'\1r',r['district_as_published'])
assert len(rows)==35*30*6, len(rows)
with open('price_statistics_odisha_2020_raw_long.csv','w',newline='') as f:
    wr=csv.DictWriter(f,fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
for r in report:
    if 'district rows' not in r or r[-1]!=30: print(r)
print(len(rows))
