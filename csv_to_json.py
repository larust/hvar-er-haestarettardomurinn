# convert_csv_to_json.py
import csv, json, collections, pathlib
#csv_path  = pathlib.Path('haestarettardomar.csv')
csv_path  = pathlib.Path('domar_og_akvardanir.csv')
json_path = pathlib.Path('mapping_d_og_a.json')

grouped = collections.defaultdict(list)
with csv_path.open(encoding='utf-8-sig', newline='') as f:
    for row in csv.DictReader(f):
        grouped[row['appeal'].strip()].append({
            'appeal' : row['appeal'].strip(),
            'supreme': row['supreme'].strip(),
            'url'    : row['url'].strip(),
            'type'    : row['type'].strip()
        })

# if a key has exactly one verdict, store just the object (smaller JSON)
mapping = {k: v[0] if len(v) == 1 else v for k, v in grouped.items()}

json_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'Wrote {json_path} with {sum(len(v) if isinstance(v,list) else 1 for v in mapping.values()):,} verdict links')
