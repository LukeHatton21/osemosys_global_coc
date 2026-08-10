"""Function to extract cost of capital values for discounting purposes within the capital recovery factor calculations."""

import pandas as pd
import numpy as np
import logging
import yaml
import os


# ── Constants ─────────────────────────────────────────────────────────────────
SCENARIO_COLUMNS = ["SSP1", "SSP2", "SSP3", "SSP4", "SSP5"]

def get_country_from_tech(tech_name: str) -> str:
    """Extract 3-letter country code from OSeMOSYS tech name.
    e.g. 'PWRSPVINDXX01' → 'IND'
    """
    return tech_name[6:9]


def get_tech_type_from_tech(tech_name: str) -> str:
    """Extract 3-letter tech type from OSeMOSYS tech name.
    e.g. 'PWRSPVINDXX01' → 'SPV'
    """
    return tech_name[3:6]


def get_country_from_node(node: str) -> str:
    """Extract 3-letter country code from OSeMOSYS node name.
    e.g. 'INDXX' → 'IND'
    """
    return node[:3]

def load_discount_rates(config: dict) -> pd.DataFrame:
    """
    Load and validate the discount rates CSV, selecting the
    correct scenario column from config.yaml.

    Returns a long-format DataFrame with columns:
        [COUNTRY, TECH_TYPE, YEAR, VALUE]
    """
    path     = config["discount_rate_idv_data"]
    scenario = config["discount_rate_idv_scenario"]

    df = pd.read_csv(path)

    # ── Validate scenario column exists ──────────────────────────────────────
    if scenario not in df.columns:
        raise ValueError(
            f"Scenario '{scenario}' not found in {path}.\n"
            f"Available scenarios: {[c for c in df.columns if c in SCENARIO_COLUMNS]}"
        )

    # ── Select only the chosen scenario column ────────────────────────────────
    df = df[["COUNTRY", "TECH_TYPE", "YEAR", scenario]].copy()
    df = df.rename(columns={scenario: "VALUE"})
    df["YEAR"] = df["YEAR"].astype(int)

    return df

def expand_to_model_years(
    df: pd.DataFrame,
    model_years: list[int],
    default_rate: float
) -> pd.DataFrame:
    """
    For each [COUNTRY, TECH_TYPE] combination, forward-fill rates across
    all model years. Years before the first specified year use the
    default_rate fallback.

    Returns a fully expanded DataFrame with every [COUNTRY, TECH_TYPE, YEAR]
    combination present.
    """
    groups = []

    for (country, tech_type), group in df.groupby(["COUNTRY", "TECH_TYPE"]):
        # Reindex to all model years
        group = (
            group
            .set_index("YEAR")
            .reindex(model_years)
        )
        group["COUNTRY"]   = country
        group["TECH_TYPE"] = tech_type

        # Forward-fill from last known value, then backward-fill
        # with default_rate for years before first specified year
        group["VALUE"] = (
            group["VALUE"]
            .ffill()                        # forward-fill gaps
            .fillna(default_rate)           # fill any remaining NaN (before first year)
        )

        group = group.reset_index().rename(columns={"index": "YEAR"})
        groups.append(group)

    return pd.concat(groups, ignore_index=True)


def build_complete_rate_table(
    df: pd.DataFrame,
    geographic_scope: list[str],
    tech_list: list[str],
    model_years: list[int],
    default_rate: float
) -> pd.DataFrame:
    """
    Apply the three-level priority fallback for each [COUNTRY, TECH, YEAR]:

        Check 1: Explicit [COUNTRY, TECH_TYPE, YEAR] entry
        Check 2: [COUNTRY, ALL, YEAR] entry
        Check 3: Global default_rate from config.yaml

    Returns a DataFrame with columns [COUNTRY, TECH_TYPE, YEAR, VALUE]
    containing only explicit technology entries (no ALL rows).
    """
    countries_in_scope = list({get_country_from_node(n) for n in geographic_scope})

    if not df.empty:
        df_spec = df[df["TECH_TYPE"] != "ALL"]
        df_all = df[df["TECH_TYPE"] == "ALL"]

        spec_lookup = (
            df_spec
                .set_index(["COUNTRY", "TECH_TYPE", "YEAR"])["VALUE"]
                .to_dict()
        )
        all_lookup = (
            df_all
                .set_index(["COUNTRY", "YEAR"])["VALUE"]
                .to_dict()
        )
    else:
        spec_lookup = {}
        all_lookup = {}

    records = []

    for country in countries_in_scope:
        # Get all unique tech types active for this country
        country_tech_types = list({
            get_tech_type_from_tech(t)
            for t in tech_list
            if get_country_from_tech(t) == country
        })

        for tech_type in country_tech_types:
            for year in model_years:

                # ── Priority 1: Explicit [COUNTRY, TECH_TYPE, YEAR] ───────────
                if (country, tech_type, year) in spec_lookup:
                    value = spec_lookup[(country, tech_type, year)]

                # ── Priority 2: [COUNTRY, ALL, YEAR] ─────────────────────────
                elif (country, year) in all_lookup:
                    value = all_lookup[(country, year)]

                # ── Priority 3: Global default ────────────────────────────────
                else:
                    value = default_rate

                # Convert from percentage terms into the required format, if required.
                if value > 1:
                    value = value / 100

                records.append({
                    "COUNTRY": country,
                    "TECH_TYPE": tech_type,
                    "YEAR": year,
                    "VALUE": value
                })

    return pd.DataFrame(records, columns=["COUNTRY", "TECH_TYPE", "YEAR", "VALUE"])

def map_to_osemosys_format(
    df: pd.DataFrame,
    tech_list: list[str],
    region: str
) -> pd.DataFrame:
    """
    Map [COUNTRY, TECH_TYPE, YEAR, VALUE] to OSeMOSYS format:
        [REGION, TECHNOLOGY, YEAR, VALUE]

    Matches on country code and tech type embedded in the full
    OSeMOSYS technology name.
    """
    records = []

    for _, row in df.iterrows():
        # Find all full tech names matching this country + tech_type
        matching_techs = [
            t for t in tech_list
            if get_country_from_tech(t) == row["COUNTRY"]
            and get_tech_type_from_tech(t) == row["TECH_TYPE"]
        ]
        for tech in matching_techs:
            records.append({
                "REGION":     region,
                "TECHNOLOGY": tech,
                "YEAR":       int(row["YEAR"]),
                "VALUE":      row["VALUE"]
            })

    return pd.DataFrame(records, columns=["REGION", "TECHNOLOGY", "YEAR", "VALUE"])


# ── Master Function ────────────────────────────────────────────────────────────

def get_discount_rate_idv(
    config: dict,
    tech_list: list[str],
    model_years: list[int],
    region: str
) -> pd.DataFrame:
    """
    Master function — orchestrates all steps and returns the final
    DiscountRateIdv DataFrame ready to write to CSV.

    Reads geographic_scope directly from config to ensure all
    countries in scope receive a value, even if not in discount_rates.csv.

    Output columns: [REGION, TECHNOLOGY, YEAR, VALUE]
    """
    default_rate     = config.get("discount_rate", 0.1)
    geographic_scope = config.get("geographic_scope", [])

    # Step 1 — Load CSV and select scenario column
    df_raw = load_discount_rates(config)

    # Step 2 — Expand specified rows to all model years
    df_expanded = expand_to_model_years(df_raw, model_years, default_rate)

    # Step 3 — Build complete table covering all scope countries/techs/years
    df_complete = build_complete_rate_table(
        df_expanded,
        geographic_scope,
        tech_list,
        model_years,
        default_rate
    )

    # Step 4 — Map to OSeMOSYS format
    df_osemosys = map_to_osemosys_format(df_complete, tech_list, region)

    return df_osemosys



if "snakemake" in globals():
    logging.basicConfig(
        filename=snakemake.log[0],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    config = snakemake.params.config
    tech_list_f = snakemake.input.tech_list
    year_list_f = snakemake.input.year_list
    out_csv = snakemake.output.csv

else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if len(sys.argv) != 4:
        msg = "Usage: python {} <config.yaml> <TECHNOLOGY.csv> <YEAR.csv>"
        print(msg.format(sys.argv[0]))
        sys.exit(1)

    with open(sys.argv[1]) as f:
        config = yaml.safe_load(f)

    tech_list_f = sys.argv[2]
    year_list_f = sys.argv[3]
    out_csv = "results/data/DiscountRateIdv.csv"

# ── Read inputs ────────────────────────────────────────────────────────────────
tech_df = pd.read_csv(tech_list_f)
tech_col = "VALUE" if "VALUE" in tech_df.columns else tech_df.columns[0]
tech_list = tech_df[tech_col].tolist()
logger.info(f"Technologies loaded: {len(tech_list)}")
logger.info(f"Sample: {tech_list[:5]}")

year_df = pd.read_csv(year_list_f)
year_col = "VALUE" if "VALUE" in year_df.columns else year_df.columns[0]
model_years = sorted(year_df[year_col].astype(int).tolist())
logger.info(f"Model years: {model_years}")

region = "GLOBAL"

# ── Run ────────────────────────────────────────────────────────────────────────
df_out = get_discount_rate_idv(
    config=config,
    tech_list=tech_list,
    model_years=model_years,
    region=region
)

# ── Write ──────────────────────────────────────────────────────────────────────
df_out.to_csv(out_csv, index=False)
logger.info(f"Written to: {out_csv}")