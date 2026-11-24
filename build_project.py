"""Build the Nancy Property Price Analysis portfolio project from public official APIs."""
from __future__ import annotations

import csv
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import matplotlib.pyplot as plt
from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
ASSETS = ROOT / "assets"
DASHBOARD = ROOT / "dashboard"
for directory in (RAW, PROCESSED, ASSETS, DASHBOARD):
    directory.mkdir(parents=True, exist_ok=True)

DATASET_ID = "5cc1b94a634f4165e96436c1"
NANCY_INSEE = "54395"
YEARS = (2023, 2024, 2025)


def get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "portfolio-project/1.0", "Accept": "application/json"})
    with urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def resource_ids() -> dict[int, str]:
    dataset = get_json(f"https://www.data.gouv.fr/api/1/datasets/{DATASET_ID}/")
    ids = {}
    for resource in dataset["resources"]:
        title = resource.get("title", "")
        for year in YEARS:
            if title == f"DVF {year}":
                ids[year] = resource["id"]
    missing = set(YEARS).difference(ids)
    if missing:
        raise RuntimeError(f"Could not resolve current DVF resource ids for: {sorted(missing)}")
    (RAW / "data_gouv_dataset_metadata.json").write_text(json.dumps(dataset, ensure_ascii=False, indent=2), encoding="utf-8")
    return ids


def fetch_year(year: int, resource_id: str) -> pd.DataFrame:
    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "page": page,
            "page_size": 200,
            "code_commune__exact": NANCY_INSEE,
            "type_local__exact": "Appartement",
            "nature_mutation__exact": "Vente",
        }
        url = f"https://tabular-api.data.gouv.fr/api/resources/{resource_id}/data/?" + urlencode(params)
        response = get_json(url)
        chunk = response.get("data", [])
        rows.extend(chunk)
        meta = response.get("meta", {})
        if not response.get("links", {}).get("next") or not chunk:
            break
        page += 1
        time.sleep(0.04)
    frame = pd.DataFrame(rows)
    frame.to_csv(RAW / f"dvf_nancy_{year}.csv", index=False, quoting=csv.QUOTE_MINIMAL)
    return frame


def get_iris() -> dict:
    url = (
        "https://services.arcgis.com/d3voDfTFbHOCRwVR/ArcGIS/rest/services/"
        "Contours_IRIS_2025__WME_/FeatureServer/0/query?"
        "where=code_insee%3D%2754395%27&outFields=*&f=geojson"
    )
    geojson = get_json(url)
    (RAW / "nvidia_iris_nancy.geojson").write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    return geojson


def point_in_ring(x: float, y: float, ring: list[list[float]]) -> bool:
    inside = False
    if len(ring) < 3:
        return False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        crossing = (yi > y) != (yj > y)
        if crossing and x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def point_in_geometry(x: float, y: float, geometry: dict) -> bool:
    if geometry.get("type") == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry.get("type") == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        return False
    for polygon in polygons:
        if point_in_ring(x, y, polygon[0]) and not any(point_in_ring(x, y, hole) for hole in polygon[1:]):
            return True
    return False


def assign_iris(frame: pd.DataFrame, iris_geojson: dict) -> pd.DataFrame:
    features = iris_geojson["features"]
    assignments = []
    for row in frame[["longitude", "latitude"]].itertuples(index=False):
        lon, lat = row
        assigned = (None, "Outside or missing IRIS")
        if pd.notna(lon) and pd.notna(lat):
            for feature in features:
                if point_in_geometry(float(lon), float(lat), feature["geometry"]):
                    props = feature["properties"]
                    assigned = (props["code_iris"], props["nom_iris"])
                    break
        assignments.append(assigned)
    result = frame.copy()
    result[["iris_code", "iris_name"]] = pd.DataFrame(assignments, index=result.index)
    return result


def clean_transactions(raw: pd.DataFrame, iris_geojson: dict) -> pd.DataFrame:
    frame = raw.copy()
    frame["date_mutation"] = pd.to_datetime(frame["date_mutation"], errors="coerce")
    for column in ("valeur_fonciere", "surface_reelle_bati", "longitude", "latitude"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.loc[
        frame["date_mutation"].notna()
        & (frame["valeur_fonciere"] > 0)
        & (frame["surface_reelle_bati"] > 0)
    ].copy()
    dedupe = ["id_mutation", "numero_disposition", "type_local", "surface_reelle_bati", "adresse_nom_voie", "date_mutation"]
    frame = frame.drop_duplicates(dedupe).copy()
    frame["year"] = frame["date_mutation"].dt.year.astype(int)
    frame["sale_value_eur"] = frame["valeur_fonciere"].round(2)
    frame["surface_m2"] = frame["surface_reelle_bati"].round(1)
    frame["price_per_m2"] = (frame["sale_value_eur"] / frame["surface_m2"]).round(2)
    frame["is_outlier"] = 0
    for year, index in frame.groupby("year").groups.items():
        values = frame.loc[index, "price_per_m2"]
        q1, q3 = values.quantile([0.25, 0.75])
        iqr = q3 - q1
        frame.loc[index, "is_outlier"] = ((values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)).astype(int)
    frame = assign_iris(frame, iris_geojson)
    keep = [
        "id_mutation", "date_mutation", "year", "sale_value_eur", "surface_m2", "price_per_m2",
        "adresse_nom_voie", "code_postal", "iris_code", "iris_name", "longitude", "latitude", "is_outlier",
    ]
    return frame[keep].sort_values(["date_mutation", "id_mutation"]).reset_index(drop=True)


def summarise(clean: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    analysis = clean.loc[(clean["is_outlier"] == 0) & clean["iris_code"].notna()].copy()
    year_summary = analysis.groupby("year").agg(
        transactions=("id_mutation", "count"),
        median_price_per_m2=("price_per_m2", "median"),
        avg_price_per_m2=("price_per_m2", "mean"),
        median_surface_m2=("surface_m2", "median"),
    ).reset_index()
    year_summary[["median_price_per_m2", "avg_price_per_m2", "median_surface_m2"]] = year_summary[["median_price_per_m2", "avg_price_per_m2", "median_surface_m2"]].round(1)
    zone = analysis.groupby(["year", "iris_code", "iris_name"]).agg(
        transactions=("id_mutation", "count"),
        median_price_per_m2=("price_per_m2", "median"),
        avg_price_per_m2=("price_per_m2", "mean"),
        median_surface_m2=("surface_m2", "median"),
    ).reset_index()
    zone[["median_price_per_m2", "avg_price_per_m2", "median_surface_m2"]] = zone[["median_price_per_m2", "avg_price_per_m2", "median_surface_m2"]].round(1)
    zone["price_rank"] = zone.groupby("year")["median_price_per_m2"].rank(method="dense", ascending=False).astype(int)
    zone["previous_year_median_price_per_m2"] = zone.sort_values("year").groupby("iris_code")["median_price_per_m2"].shift(1)
    zone["yoy_price_change_pct"] = (
        100 * (zone["median_price_per_m2"] - zone["previous_year_median_price_per_m2"])
        / zone["previous_year_median_price_per_m2"]
    ).round(1)
    return year_summary, zone.sort_values(["year", "price_rank", "iris_name"])


def plot_dashboard(clean: pd.DataFrame, year_summary: pd.DataFrame, zone: pd.DataFrame, iris_geojson: dict) -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    fig, axes = plt.subplots(2, 2, figsize=(16, 11), constrained_layout=True)
    fig.suptitle("Nancy Property Price Analysis", fontsize=20, fontweight="bold", x=0.05, ha="left")
    latest_year = int(year_summary["year"].max())
    axes[0, 0].plot(year_summary["year"], year_summary["median_price_per_m2"], marker="o", linewidth=2.7, color="#1F4E79")
    axes[0, 0].set_title("Median apartment price per m2", loc="left", fontweight="bold")
    axes[0, 0].set_ylabel("EUR / m2")
    for x, y in zip(year_summary["year"], year_summary["median_price_per_m2"]):
        axes[0, 0].annotate(f"EUR {y:,.0f}", (x, y), xytext=(0, 9), textcoords="offset points", ha="center", fontsize=9)

    latest_zone = zone.loc[zone["year"] == latest_year].sort_values("median_price_per_m2", ascending=True).tail(10)
    axes[0, 1].barh(latest_zone["iris_name"], latest_zone["median_price_per_m2"], color="#4E79A7")
    axes[0, 1].set_title(f"Highest median-price IRIS areas ({latest_year})", loc="left", fontweight="bold")
    axes[0, 1].set_xlabel("EUR / m2")

    display = clean.loc[clean["is_outlier"] == 0]
    for year, frame in display.groupby("year"):
        axes[1, 0].scatter(frame["surface_m2"], frame["price_per_m2"], alpha=0.38, s=12, label=str(year))
    axes[1, 0].set_title("Price per m2 versus apartment surface", loc="left", fontweight="bold")
    axes[1, 0].set_xlabel("Surface (m2)")
    axes[1, 0].set_ylabel("EUR / m2")
    axes[1, 0].legend(frameon=False, title="Year")

    values = (
        zone.loc[zone["year"] == latest_year]
        .assign(iris_code=lambda frame: frame["iris_code"].astype(str))
        .set_index("iris_code")["median_price_per_m2"]
        .to_dict()
    )
    patches, colors = [], []
    all_values = list(values.values()) or [0]
    low, high = min(all_values), max(all_values)
    cmap = plt.get_cmap("YlOrRd")
    for feature in iris_geojson["features"]:
        geom = feature["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        value = values.get(feature["properties"]["code_iris"])
        color = "#eeeeee" if value is None else cmap((value - low) / ((high - low) or 1))
        for polygon in polys:
            patches.append(Polygon(polygon[0], closed=True))
            colors.append(color)
    collection = PatchCollection(patches, facecolor=colors, edgecolor="white", linewidth=0.35)
    axes[1, 1].add_collection(collection)
    axes[1, 1].autoscale_view()
    axes[1, 1].set_aspect("equal")
    axes[1, 1].set_title(f"IRIS median price per m2 ({latest_year})", loc="left", fontweight="bold")
    axes[1, 1].set_axis_off()
    for ax in axes.flat[:3]:
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(ASSETS / "dashboard_preview.png", dpi=180, bbox_inches="tight")
    plt.close(fig)

    current = year_summary.loc[year_summary["year"] == latest_year].iloc[0]
    top = latest_zone.iloc[-1]
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Nancy Property Price Analysis</title>
    <style>body{{font-family:Arial,sans-serif;margin:40px;color:#17212b}}h1{{margin-bottom:4px}}.sub{{color:#54616d}}.cards{{display:flex;gap:16px;flex-wrap:wrap;margin:24px 0}}.card{{border:1px solid #d8dee4;border-radius:10px;padding:16px;min-width:200px}}.value{{font-size:28px;font-weight:700;color:#1f4e79}}img{{width:100%;max-width:1200px;border:1px solid #d8dee4;border-radius:10px}}</style>
    </head><body><h1>Nancy Property Price Analysis</h1><p class='sub'>Official data.gouv.fr DVF transaction data | Last project refresh: {datetime.now(timezone.utc).date()}</p>
    <section class='cards'><div class='card'><div>Median price per m2 ({latest_year})</div><div class='value'>EUR {current.median_price_per_m2:,.0f}</div></div><div class='card'><div>Analysed transactions ({latest_year})</div><div class='value'>{int(current.transactions):,}</div></div><div class='card'><div>Top IRIS by median price</div><div class='value' style='font-size:17px'>{top.iris_name}</div></div></section>
    <img src='../assets/dashboard_preview.png' alt='Dashboard preview'><p>This is an educational analysis, not a property valuation. See the README for methods and limitations.</p></body></html>"""
    (DASHBOARD / "index.html").write_text(html, encoding="utf-8")


def main() -> None:
    ids = resource_ids()
    frames = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {pool.submit(fetch_year, year, ids[year]): year for year in YEARS}
        for future in as_completed(futures):
            frames.append(future.result())
    raw = pd.concat(frames, ignore_index=True)
    iris = get_iris()
    clean = clean_transactions(raw, iris)
    year_summary, zone_summary = summarise(clean)
    clean.to_csv(PROCESSED / "transactions_clean.csv", index=False)
    year_summary.to_csv(PROCESSED / "year_summary.csv", index=False)
    zone_summary.to_csv(PROCESSED / "iris_year_summary.csv", index=False)
    with sqlite3.connect(PROCESSED / "property_analysis.sqlite") as connection:
        clean.to_sql("transactions_clean", connection, if_exists="replace", index=False)
        year_summary.to_sql("year_summary", connection, if_exists="replace", index=False)
        zone_summary.to_sql("iris_year_summary", connection, if_exists="replace", index=False)
    plot_dashboard(clean, year_summary, zone_summary, iris)
    print("Nancy project built successfully.")


if __name__ == "__main__":
    main()
