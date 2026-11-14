import json, sys
from shapely.geometry import shape, mapping
from shapely.ops import unary_union
from shapely import set_precision
adm1 = json.load(open(sys.argv[1])); adm0 = json.load(open(sys.argv[2]))
idn1 = {f['properties']['iso_3166_2']: f for f in adm1['features'] if f['properties'].get('adm0_a3') == 'IDN'}
TOL = 0.002
def clean(g):
    g = g.simplify(TOL, preserve_topology=True)
    g = set_precision(g, 1e-5)
    if not g.is_valid: g = g.buffer(0)
    return g
def prov(code): return shape(idn1[code]['geometry'])
feats = []
idn0 = [f for f in adm0['features'] if f['properties'].get('ADM0_A3') == 'IDN'][0]
SRC = "Natural Earth 1:10m Cultural Vectors (v5.x, nvkelso/natural-earth-vector)"
LIC = "Public domain (Natural Earth terms of use)"
def add(id_, name, kind, geom, members, note):
    g = clean(geom)
    feats.append({"type":"Feature","properties":{"id":id_,"name":name,"kind":kind,"members":members,
      "source":SRC,"license":LIC,"note":note,"simplification_tolerance_deg":TOL},"geometry":mapping(g)})
add("indonesia","Indonesia (national land boundary)","country",shape(idn0['geometry']),["IDN"],"Natural Earth admin-0 land boundary; excludes surrounding sea.")
SUM = ["ID-AC","ID-SU","ID-SB","ID-RI","ID-JA","ID-SS","ID-BE","ID-LA"]
add("sumatra","Sumatra (8 provinces)","province-group",unary_union([prov(c) for c in SUM]),SUM,"Union of the 8 provinces on Sumatra, including their small offshore islands. Excludes Riau Islands and Bangka-Belitung provinces.")
KAL = ["ID-KB","ID-KT","ID-KS","ID-KI"]
add("kalimantan","Kalimantan (Indonesian Borneo)","province-group",unary_union([prov(c) for c in KAL]),KAL,"Union of Indonesian provinces on Borneo as delineated in Natural Earth (East Kalimantan polygon includes present-day North Kalimantan). Excludes Malaysian and Bruneian Borneo.")
for code,name in [("ID-RI","Riau"),("ID-JA","Jambi"),("ID-SS","South Sumatra"),("ID-KB","West Kalimantan"),("ID-KT","Central Kalimantan"),("ID-KS","South Kalimantan"),("ID-KI","East Kalimantan (incl. North Kalimantan)")]:
    add("prov-"+code.lower(), name+" province","province",prov(code),[code],"Natural Earth admin-1 province boundary.")
json.dump({"type":"FeatureCollection","features":feats}, open(sys.argv[3],"w"), separators=(",",":"))
for f in feats: print(f['properties']['id'], shape(f['geometry']).is_valid, len(json.dumps(f['geometry'])))
