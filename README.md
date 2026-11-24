# Nancy Property Price Analysis

![Dashboard preview](assets/dashboard_preview.png)

## Why Nancy, not Metz?

The official French DVF transaction dataset excludes Moselle, which includes
Metz. It therefore cannot support a truthful transaction-level Metz project.
Nancy is a nearby Grand Est city that is covered by DVF, allowing this project
to remain reproducible using a public government source.

## Business question

How did apartment price per m2, transaction volume and price dispersion evolve
across Nancy's IRIS neighbourhoods from 2023 to 2025?

## What this project does

1. Queries official data.gouv.fr geolocated DVF records for Nancy
   (`code_commune=54395`).
2. Keeps arms-length apartment sales with a positive sale value and built area.
3. Calculates price per m2 and flags annual IQR outliers.
4. Assigns transactions to INSEE/IGN IRIS neighbourhood boundaries using a
   point-in-polygon join.
5. Uses SQLite window functions to rank neighbourhoods and calculate annual
   changes.
6. Generates dashboard-ready CSVs, a SQLite database and a visual dashboard.

## Data sources

- [DVF geolocated transactions - data.gouv.fr](https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees)
- [INSEE/IGN Contours IRIS](https://www.insee.fr/fr/information/2017372)

## Reproduce

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python src/build_project.py
```

## Dashboard pages

1. **Market overview** - median price per m2, transaction count and annual trend.
2. **Neighbourhood comparison** - IRIS price ranking and year-over-year changes.
3. **Distribution and outliers** - price versus surface, with annual IQR flags.
4. **Spatial view** - IRIS choropleth for the most recent year.

## Power BI

Import `data/processed/transactions_clean.csv` and
`data/processed/iris_year_summary.csv`, then follow
[`powerbi/PowerBI_Build_Guide.md`](powerbi/PowerBI_Build_Guide.md). The project
includes DAX measures and a Power Query starter.

## Cleaning rules

- `nature_mutation = Vente`
- `type_local = Appartement`
- positive sale value and built surface
- duplicate property rows removed using transaction and property attributes
- annual IQR method used to flag, rather than silently delete, extreme price/m2
  values

## Disclaimer

This is an educational analysis and not a property valuation. DVF records are
administrative transaction records; data quality, transaction composition and
outliers can affect results.
