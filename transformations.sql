-- Run after src/build_project.py creates data/processed/property_analysis.sqlite.

WITH zone_year AS (
    SELECT
        year,
        iris_code,
        iris_name,
        COUNT(*) AS transactions,
        ROUND(AVG(price_per_m2), 0) AS avg_price_per_m2,
        ROUND(AVG(surface_m2), 1) AS avg_surface_m2
    FROM transactions_clean
    WHERE is_outlier = 0
      AND iris_code IS NOT NULL
    GROUP BY year, iris_code, iris_name
), ranked AS (
    SELECT
        *,
        DENSE_RANK() OVER (
            PARTITION BY year ORDER BY avg_price_per_m2 DESC
        ) AS price_rank,
        LAG(avg_price_per_m2) OVER (
            PARTITION BY iris_code ORDER BY year
        ) AS previous_year_avg_price_per_m2
    FROM zone_year
)
SELECT
    year,
    iris_name,
    transactions,
    avg_price_per_m2,
    price_rank,
    ROUND(
        100.0 * (avg_price_per_m2 - previous_year_avg_price_per_m2)
        / previous_year_avg_price_per_m2,
        1
    ) AS yoy_price_change_pct
FROM ranked
ORDER BY year DESC, price_rank, iris_name;

-- Outlier audit: retain flags so the analysis is transparent.
SELECT
    year,
    COUNT(*) AS records,
    SUM(is_outlier) AS flagged_outliers,
    ROUND(100.0 * SUM(is_outlier) / COUNT(*), 2) AS flagged_outlier_pct
FROM transactions_clean
GROUP BY year
ORDER BY year;
