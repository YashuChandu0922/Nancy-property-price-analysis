# Power BI build guide

## Import

Import from `data/processed/`:

- `transactions_clean.csv`
- `iris_year_summary.csv`
- `year_summary.csv`

Create a calendar table based on `date_mutation` and relate it to
`transactions_clean[date_mutation]`.

## Page 1 - Market overview

- Cards: Transaction Count, Median Price per m2, Outlier Rate %
- Line chart: Year vs median price per m2
- Clustered columns: Year vs transaction count

## Page 2 - Neighbourhood comparison

- Bar chart: IRIS name vs median price per m2, filtered to latest year
- Matrix: IRIS name, year, transaction count, median price per m2, YoY change
- Slicer: year, outlier flag

## Page 3 - Distribution and outliers

- Scatter: surface_m2 vs price_per_m2, details `id_mutation`, legend outlier flag
- Histogram: price_per_m2 bins

## Page 4 - Spatial view

Join `iris_year_summary` to an IRIS shape source on `iris_code` and build a
filled map for median price per m2. The included Python preview performs the
same spatial join with the official INSEE/IGN IRIS boundary source.

Use `Measures.dax` and `Power_Query_M.txt` as your starting point.
