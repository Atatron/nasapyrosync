"""Regenerate regions.geojson: keep the Natural Earth national/island features unchanged, replace the provinces with
the 38 BIG-based provinces trimmed to the national outline. Args: <existing regions.geojson> <BIG provinces json> <out>"""
import json, sys
from shapely.geometry import shape, mapping, Polygon, MultiPolygon
from shapely import set_precision, make_valid
from shapely.ops import unary_union
old = json.load(open(sys.argv[1]))['features']
big = json.load(open(sys.argv[2]))['features']
keep = [f for f in old if f['properties']['kind'] != 'province']
assert [f['properties']['id'] for f in keep] == ['indonesia', 'sumatra', 'kalimantan'], [f['properties']['id'] for f in keep]
NAT = shape(keep[0]['geometry'])
TOL = 0.002
CODES = {  # BIG name -> (ISO 3166-2, English name)
 'Aceh':('ID-AC','Aceh'),'Sumatera Utara':('ID-SU','North Sumatra'),'Sumatera Barat':('ID-SB','West Sumatra'),'Riau':('ID-RI','Riau'),
 'Kepulauan Riau':('ID-KR','Riau Islands'),'Jambi':('ID-JA','Jambi'),'Bengkulu':('ID-BE','Bengkulu'),'Sumatera Selatan':('ID-SS','South Sumatra'),
 'Kepulauan Bangka Belitung':('ID-BB','Bangka Belitung Islands'),'Lampung':('ID-LA','Lampung'),'DKI Jakarta':('ID-JK','Jakarta'),
 'Jawa Barat':('ID-JB','West Java'),'Banten':('ID-BT','Banten'),'Jawa Tengah':('ID-JT','Central Java'),'Daerah Istimewa Yogyakarta':('ID-YO','Yogyakarta'),
 'Jawa Timur':('ID-JI','East Java'),'Bali':('ID-BA','Bali'),'Nusa Tenggara Barat':('ID-NB','West Nusa Tenggara'),'Nusa Tenggara Timur':('ID-NT','East Nusa Tenggara'),
 'Kalimantan Barat':('ID-KB','West Kalimantan'),'Kalimantan Tengah':('ID-KT','Central Kalimantan'),'Kalimantan Selatan':('ID-KS','South Kalimantan'),
 'Kalimantan Timur':('ID-KI','East Kalimantan'),'Kalimantan Utara':('ID-KU','North Kalimantan'),'Sulawesi Utara':('ID-SA','North Sulawesi'),
 'Gorontalo':('ID-GO','Gorontalo'),'Sulawesi Tengah':('ID-ST','Central Sulawesi'),'Sulawesi Barat':('ID-SR','West Sulawesi'),
 'Sulawesi Selatan':('ID-SN','South Sulawesi'),'Sulawesi Tenggara':('ID-SG','Southeast Sulawesi'),'Maluku':('ID-MA','Maluku'),
 'Maluku Utara':('ID-MU','North Maluku'),'Papua':('ID-PA','Papua'),'Papua Barat':('ID-PB','West Papua'),'Papua Barat Daya':('ID-PD','Southwest Papua'),
 'Papua Pegunungan':('ID-PE','Highland Papua'),'Papua Selatan':('ID-PS','South Papua'),'Papua Tengah':('ID-PT','Central Papua')}
assert len(big) == 38 and set(CODES) == {f['properties']['PROVINSI'] for f in big}
def polys(g):
    if isinstance(g, (Polygon, MultiPolygon)): return g
    return MultiPolygon([p for q in getattr(g, 'geoms', []) for p in (q.geoms if isinstance(q, MultiPolygon) else [q]) if isinstance(p, Polygon)])
SRC = "Badan Informasi Geospasial (BIG) province boundaries, 38 provinces, via github.com/ardian28/GeoJson-Indonesia-38-Provinsi"
LIC = "MIT (repository); boundary data from Badan Informasi Geospasial, credited as the source"
feats = []
for f in big:
    code, name = CODES[f['properties']['PROVINSI']]
    g = make_valid(shape(f['geometry'])).intersection(NAT)
    g = polys(g).simplify(TOL, preserve_topology=True)
    g = set_precision(g, 1e-5)
    if not g.is_valid: g = g.buffer(0)
    g = polys(polys(g).intersection(NAT))  # trim again: simplify/precision can move edge vertices just outside the outline
    assert not g.is_empty and g.is_valid, name
    feats.append({"type":"Feature","properties":{"id":"prov-"+code.lower(),"name":name,"kind":"province","members":[code],
      "source":SRC,"license":LIC,"note":"BIG province boundary (includes the 2022 Papua provinces and North Kalimantan), trimmed to the "
      "Natural Earth national land outline so that province totals never exceed the Indonesia total.","simplification_tolerance_deg":TOL},
      "geometry":mapping(g)})
feats.sort(key=lambda f: f['properties']['name'])
json.dump({"type":"FeatureCollection","features":keep+feats}, open(sys.argv[3],"w"), separators=(",",":"))
U = unary_union([shape(f['geometry']) for f in feats])
print('features', len(keep)+len(feats), 'overlap', round(sum(shape(f['geometry']).area for f in feats)-U.area, 6), 'coverage of national', round(U.area/NAT.area, 4))
