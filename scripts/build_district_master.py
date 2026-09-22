"""Build the Odisha district master, alias table and a coverage report for every raw source.
Matching is deterministic: a published name is normalised (upper-case, letters only) and looked up in a curated
alias list. Nothing is fuzzy-matched at run time; new spellings fail loudly and must be added to ALIASES."""
import re
from pathlib import Path
import pandas as pd
EXT = Path(__file__).resolve().parent.parent / 'data' / 'extracted'

def norm(s): return re.sub(r'[^A-Z]', '', str(s).upper())

# district_id, display_name (spelling used most in DE&S sources), lgd_name (official, LGD), lgd_code, census_2011_code, headquarters
DISTRICTS = [
 ('OD01','Angul','Anugul',344,384,'Angul'), ('OD02','Balangir','Balangir',345,393,'Balangir'),
 ('OD03','Balasore','Baleshwar',346,377,'Balasore'), ('OD04','Bargarh','Bargarh',347,370,'Bargarh'),
 ('OD05','Bhadrak','Bhadrak',348,378,'Bhadrak'), ('OD06','Boudh','Boudh',349,391,'Boudh'),
 ('OD07','Cuttack','Cuttack',350,381,'Cuttack'), ('OD08','Deogarh','Deogarh',351,373,'Deogarh'),
 ('OD09','Dhenkanal','Dhenkanal',352,383,'Dhenkanal'), ('OD10','Gajapati','Gajapati',353,389,'Paralakhemundi'),
 ('OD11','Ganjam','Ganjam',354,388,'Chhatrapur'), ('OD12','Jagatsinghpur','Jagatsinghapur',355,380,'Jagatsinghpur'),
 ('OD13','Jajpur','Jajapur',356,382,'Jajpur'), ('OD14','Jharsuguda','Jharsuguda',357,371,'Jharsuguda'),
 ('OD15','Kalahandi','Kalahandi',358,395,'Bhawanipatna'), ('OD16','Kandhamal','Kandhamal',359,390,'Phulbani'),
 ('OD17','Kendrapara','Kendrapara',360,379,'Kendrapara'), ('OD18','Keonjhar','Kendujhar',361,375,'Keonjhar'),
 ('OD19','Khordha','Khordha',362,386,'Khordha'), ('OD20','Koraput','Koraput',363,398,'Koraput'),
 ('OD21','Malkangiri','Malkangiri',364,399,'Malkangiri'), ('OD22','Mayurbhanj','Mayurbhanj',365,376,'Baripada'),
 ('OD23','Nabarangpur','Nabarangpur',366,397,'Nabarangpur'), ('OD24','Nayagarh','Nayagarh',367,385,'Nayagarh'),
 ('OD25','Nuapada','Nuapada',368,394,'Nuapada'), ('OD26','Puri','Puri',369,387,'Puri'),
 ('OD27','Rayagada','Rayagada',370,396,'Rayagada'), ('OD28','Sambalpur','Sambalpur',371,372,'Sambalpur'),
 ('OD29','Subarnapur','Subarnapur',372,392,'Sonepur'), ('OD30','Sundargarh','Sundargarh',373,374,'Sundargarh'),
]
# Every spelling actually seen in the sources (plus official names), mapped by hand.
ALIASES = {
 'OD01':['Angul','ANGUL','Anugul','ANUGUL'],
 'OD02':['Balangir','BALANGIR','Bolangir','Bolangiri'],
 'OD03':['Balasore','BALASORE','Baleshwar'],
 'OD04':['Bargarh','BARGARH','Baragarh','BARAGARH'],
 'OD05':['Bhadrak','BHADRAK'],
 'OD06':['Boudh','BOUDH','Boudha','Baudh'],
 'OD07':['Cuttack','CUTTACK'],
 'OD08':['Deogarh','DEOGARH','Debagarh'],
 'OD09':['Dhenkanal','DHENKANAL'],
 'OD10':['Gajapati','GAJAPATI','Gajpati'],
 'OD11':['Ganjam','GANJAM'],
 'OD12':['Jagatsinghpur','JAGATSINGHPUR','Jagatsinghapur','Jagathsinghpur','Jagatsingpur','Jagatsinpur','J.Singhpur'],
 'OD13':['Jajpur','JAJPUR','Jajapur'],
 'OD14':['Jharsuguda','JHARSUGUDA','Jharasuguda','Jharsuguda*'],
 'OD15':['Kalahandi','KALAHANDI'],
 'OD16':['Kandhamal','KANDHAMAL'],
 'OD17':['Kendrapara','KENDRAPARA','Kendrapada'],
 'OD18':['Keonjhar','KEONJHAR','Kendujhar','Keunjhor'],
 'OD19':['Khordha','Khurda','KHURDA'],
 'OD20':['Koraput','KORAPUT'],
 'OD21':['Malkangiri','MALKANGIRI','Malakangiri','Malkanagir','Malkanagiri'],
 'OD22':['Mayurbhanj','MAYURBHANJ','Mayurbhanja'],
 'OD23':['Nabarangpur','Nabarangapur','Nabrangpur','Nawarangpur','NAWARANGPUR','Nawrangpur','Nowaragpur','NOWARAGPUR','Nowarangpur','Nowrangapur'],
 'OD24':['Nayagarh','NAYAGARH','Nayagada'],
 'OD25':['Nuapada','NUAPADA','Nuapara'],
 'OD26':['Puri','PURI'],
 'OD27':['Rayagada','RAYAGADA','Raygada','RAYGADA','Rayagarh'],
 'OD28':['Sambalpur','SAMBALPUR'],
 'OD29':['Subarnapur','SUBARNAPUR','Subarnpur','Sonepur'],
 'OD30':['Sundargarh','SUNDARGARH','Sundergarh'],
}
STATE_LABELS = ['STATE','ORISSA  STATE','Odisha','TOTAL','Total','Grand Total']   # rows that are state totals, not districts

# Labels known not to be districts (region groupings, crop names and notes picked up from report/OES text)
NOT_DISTRICT = {'BALANGIRBARGARH','KALAHANDIRAYAGADA','JHARSUGUDASAMBALPURANUGULDHENKANALDEOGARH','IE','ARTISANGRADESTONE',
                'AREAFIGURECALCULATEDWITHOUTNORMALIZATIONFACTOR','PADDY','WHEAT','MAIZE','RAGI','MUNG','BIRI','KULTHI','TIL',
                'GROUNDNUT','GROUNDNU','MUSTARD','NIGER','JUTE','POTATO','SUGARCANE','SUGARCAN'}

def build_lookup():
    lk = {}
    for did, names in ALIASES.items():
        for n in names:
            k = norm(n)
            assert lk.get(k, did) == did, f'alias collision: {n}'
            lk[k] = did
    for s in STATE_LABELS: lk[norm(s)] = 'OD00'
    return lk

def resolve(name, lookup):
    k = norm(name)
    if k in lookup: return lookup[k], ('state_total' if lookup[k] == 'OD00' else 'district')
    if k in NOT_DISTRICT or k.startswith('SOURCE'): return '', 'not_a_district_label'
    return '', 'UNRESOLVED'

if __name__ == '__main__':
    lookup = build_lookup()
    master = pd.DataFrame(DISTRICTS, columns=['district_id','display_name','lgd_name','lgd_code','census_2011_code','headquarters'])
    master['state_name'] = 'Odisha'; master['state_lgd_code'] = 21
    master['code_verification'] = 'lgd_code and census_2011_code to be verified against lgdirectory.gov.in / Census 2011 before release'
    master.to_csv(EXT / 'district_master.csv', index=False)

    h = pd.read_csv(EXT / 'harvested_names.csv')
    h[['district_id','label_type']] = h.name_as_published.apply(lambda n: pd.Series(resolve(n, lookup)))
    h['normalised_key'] = h.name_as_published.map(norm)
    h = h.merge(master[['district_id','display_name']], on='district_id', how='left')

    # The two report PDFs are scraped heuristically for aliases only; a stray line there is noise, not a data error.
    harvest_only = h.sources.str.replace('; ', ';').str.split(';').apply(lambda ss: all(':district_tables' in s for s in ss))
    h.loc[(h.label_type == 'UNRESOLVED') & harvest_only, 'label_type'] = 'unmatched_report_text'

    alias = h[h.label_type.isin(['district','state_total'])][['name_as_published','normalised_key','district_id','display_name','label_type','n_sources','occurrences','sources']]
    alias.loc[alias.label_type=='state_total','display_name'] = 'Odisha (state total)'
    # add curated aliases never seen yet (official names) so the alias table is complete
    extra = [(n, norm(n), did) for did, ns in ALIASES.items() for n in ns if norm(n) not in set(alias.normalised_key)]
    for n, k, did in extra:
        alias.loc[len(alias)] = [n, k, did, master.set_index('district_id').display_name[did], 'district', 0, 0, 'curated (official/alternate spelling, not yet seen)']
    alias.sort_values(['district_id','occurrences'], ascending=[True, False]).to_csv(EXT / 'district_aliases.csv', index=False)
    h.sort_values(['label_type','name_as_published']).to_csv(EXT / 'district_name_coverage_report.csv', index=False)

    print('districts:', len(master), '| distinct published labels:', len(h), '| aliases:', len(alias))
    print(h.label_type.value_counts().to_dict())
    print('UNRESOLVED (must be fixed):', h[h.label_type=='UNRESOLVED'].name_as_published.tolist())
    print('unmatched report text (review only):', h[h.label_type=='unmatched_report_text'].name_as_published.tolist())
    # every district must be present in every data source that is meant to cover all districts
    per_src = {}
    for _, r in h[h.label_type=='district'].iterrows():
        for s in r.sources.split('; '): per_src.setdefault(s, set()).add(r.district_id)
    short = {s: sorted(set(master.district_id) - ids) for s, ids in per_src.items() if len(ids) < 30}
    print('sources not covering all 30 districts:', {s: len(v) for s, v in short.items()})