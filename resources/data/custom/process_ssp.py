import pandas as pd

ds = pd.read_csv("SSP_WACC_SCENARIOS_CENTRAL_WIDE.csv")
selected_ds = ds.loc[(ds["Technology"]=="Commercial") & (ds["Policy Maturity"] == "Strong") & (ds["Country code"] != "N/A")]
selected_ds.columns = selected_ds.columns.astype("str")
melted_ds = pd.melt(selected_ds, id_vars=["Country Name",	"Country code", "Region", "WBG Income Group (2025)", "Scenario", "Technology", "Policy Maturity"],
    var_name="Year",
    value_name="Value")

extracted_ds = melted_ds.dropna(subset=["Country code"]).drop(columns=["Region", "WBG Income Group (2025)"])
pivot_ds = extracted_ds.pivot(index=["Country Name", "Year", "Country code", "Technology", "Policy Maturity"], columns="Scenario", values="Value").reset_index()
pivot_ds["TECH_TYPE"]="ALL"
pivot_ds.rename(columns={"Year": "YEAR", "Country code":"COUNTRY"}, inplace=True)
pivot_ds.to_csv("discount_rates.csv")