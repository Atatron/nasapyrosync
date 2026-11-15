import sys, json
from datetime import date
from collections import defaultdict
sys.path.insert(0, "/home/user/pyrosync/backend")
from pyrosync import harmonize as H, query as Q
f = Q.Filters(start=date(2012,1,20), end=date(2026,11,14), aoi="none", types=["0","unknown"])
cfg = H.HarmonizeConfig(viirs_series="VIIRS_SNPP", modis_platforms=["Aqua"], tolerance_min=30)
rep, ex = H._run(f, cfg)
ev = ex["events"]
matched = set()
dts = defaultdict(list)
for mid, vid, *rest in ex["matched"]:
    matched.add(mid-1); matched.add(vid-1)
yv = defaultdict(lambda: [0,0]); ym = defaultdict(lambda: [0,0]); hrs = defaultdict(list)
for i, r in enumerate(ev):
    y = r[6].year
    d = (yv if r[1]=="V" else ym)[y]
    d[0] += r[7]; d[1] += r[7] if i in matched else 0
    if r[1] == "M" and r[6].hour in range(3,9): hrs[y].append(r[6].hour*60+r[6].minute)
import statistics
out = {y: {"viirs_matched_share": yv[y][1]/max(yv[y][0],1), "modis_matched_share": ym[y][1]/max(ym[y][0],1),
           "aqua_day_median_utc_min": statistics.median(hrs[y]) if hrs[y] else None} for y in sorted(yv)}
json.dump(out, open(sys.argv[1], "w"), indent=1)
for y, v in out.items(): print(y, round(v["viirs_matched_share"],3), round(v["modis_matched_share"],3), v["aqua_day_median_utc_min"])
