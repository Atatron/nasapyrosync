# Scientific references (1.5)

Each entry was checked against a bibliographic record before it was included. The check date and source are given for each.
Where a check could not be repeated, that is said. Nothing here is filled in from memory.

## Sensors and products

**Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014).** The New VIIRS 375 m active fire detection data product:
Algorithm description and initial assessment. *Remote Sensing of Environment* 143, 85–96. https://doi.org/10.1016/j.rse.2013.12.008

- *Checked:* Crossref record, 2026-11-15: authors, title, journal, volume 143 and pages 85–96 match; Crossref has no issue
  number. A second check the same day reached only the DOI redirect (to Elsevier PII S0034425713004483), because the publisher
  page refuses automated access.
- *Used for:* the VIIRS 375 m detection algorithm, and why VIIRS detects many more, smaller fire pixels than MODIS. This is the
  reason raw counts are never compared or added across instruments.

**Giglio, L., Schroeder, W., & Justice, C. O. (2016).** The collection 6 MODIS active fire detection algorithm and fire products.
*Remote Sensing of Environment* 178, 31–41. https://doi.org/10.1016/j.rse.2016.02.054

- *Checked:* Crossref record, 2026-11-15: authors, title, journal, volume 178 and pages 31–41 match; Crossref has no issue
  number. The repeat check again reached only the DOI redirect (Elsevier PII S0034425716300827).
- *Used for:* the MODIS Collection 6 active-fire algorithm, on which the Terra and Aqua detections (and the MODIS-Aqua
  reference scale) are based.

**MCD64A1 Version 6.1 (061), MODIS/Terra+Aqua Burned Area Monthly L3 Global 500m SIN Grid.**

- *Recommended citation, as given on the product page:* Giglio, L., Justice, C., Boschetti, L., & Roy, D. (2021).
  *MODIS/Terra+Aqua Burned Area Monthly L3 Global 500m SIN Grid V061* [Data set]. NASA Land Processes Distributed Active Archive
  Center. https://doi.org/10.5067/MODIS/MCD64A1.061
- *Checked:* 2026-11-15. https://lpdaac.usgs.gov/products/mcd64a1v061/ now redirects to the NASA Earthdata catalog entry
  https://www.earthdata.nasa.gov/data/catalog/lpcloud-mcd64a1-061. That page gives:
  - 500 m spatial resolution, monthly temporal resolution, temporal extent 2000-11-01 to present;
  - dataset DOI 10.5067/MODIS/MCD64A1.061;
  - the page heading includes "Direct Broadcast", while the citation title does not.
- *Status in PyroSync:* **not implemented in 1.5.** It was the optional P2 item. It is the product to use for burned area,
  because FIRMS active-fire points are not burned area, and PyroSync never turns them into burned-area polygons.

## Multi-sensor fire records (related work)

**Zheng, Y., Ding, K., Xue, L., Wang, Z., Jiao, G., Zhu, Y., Zhang, J., & Ren, Q. (2026).** Fire Radiative Power Correction and
Spatiotemporal Fusion Based on MYD14 and VNP14IMG. *Remote Sensing* 18(10), 1650. https://doi.org/10.3390/rs18101650

- *Checked:* 2026-11-15 on the MDPI article page (https://www.mdpi.com/2072-4292/18/10/1650, reached from the DOI resolver).
  Title, the eight authors in order, journal, volume 18, issue 10 and article number 1650 match. It was published 20 May 2026.
  The page's machine-readable author tag lists only one name; the visible author list, used here, has eight.
- *Relation to PyroSync:* the paper corrects and fuses **fire radiative power** from Aqua MODIS (MYD14) and S-NPP VIIRS
  (VNP14IMG). PyroSync 1.5 fuses **daily detection counts** on an Aqua scale and does not fuse FRP. The paper supports the general
  approach of calibrating one sensor to another before combining them, rather than adding raw values. PyroSync's estimator, gate
  and thresholds are its own and are not taken from this paper.

## Methods used for validation (unchanged from 1.4, Crossref-checked 2026-11-15)

- Tashman, L. J. (2000). Out-of-sample tests of forecasting accuracy: an analysis and review. *International Journal of
  Forecasting* 16(4), 437–450. https://doi.org/10.1016/S0169-2070(00)00065-0 (rolling-origin evaluation).
- Hyndman, R. J., & Koehler, A. B. (2006). Another look at measures of forecast accuracy. *International Journal of Forecasting*
  22(4), 679–688. https://doi.org/10.1016/j.ijforecast.2006.03.001 (MAE and RMSE).
- Kunsch, H. R. (1989). The Jackknife and the Bootstrap for General Stationary Observations. *The Annals of Statistics* 17(3),
  1217–1241. https://doi.org/10.1214/aos/1176347265 (block bootstrap for the 95 % interval of each ratio).

## Project decisions (not from the literature)

These are project choices: the reference platform (Aqua); the gate bands 0.8–1.25× and 0.67–1.5×; 80 % of years in band; the
90th-percentile high-fire threshold; the 20 % hold-out; the 365-day transition window; the 20-row gap rule; the 0.22 screen
share of the Analyze Location circle; and the zoom-to-grid table.
