# Planning prototype (not application code)

`proto.py` compared the daily-total candidates before `aggregate.py` was written (run A split 2019-09-22; run C 2023-09-21). `A_t0.json` uses type 0 only, `A_t0u.json` types 0 + unknown (the 1.3 default, used for all 1.4 validation). `aqua_drift.py` produced `../aqua_drift_matched_share.json` (matched share per year and Aqua's median daytime acquisition time, minutes after 00:00 UTC). Run from `backend/` with `PYROSYNC_DATA_DIR` pointing at the full archive. The app's numbers come from `aggregate.py`, not from these scripts.
