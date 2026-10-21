"""Function to set AnnualEmissionLimit."""

import itertools

import pandas as pd

from data import get_years


def add_emission_limits(
    emissions,
    emission_limit,
    ember,
    start_year,
    end_year,
    region_name,
):
    """
    Create the AnnualEmissionLimit dataframe.

    For LINEAR emission limits, EMBER data is used as the historical
    baseline. If all available EMBER years occur before start_year, the
    most recent available EMBER value is added as a baseline before
    interpolation to the policy target.
    """

    # Set empty AnnualEmissionLimit dataframe.
    annual_emission_limit = pd.DataFrame(
        columns=["REGION", "EMISSION", "YEAR", "VALUE"]
    )

    # Check whether emission limits exist.
    if not emission_limit:
        return annual_emission_limit

    # Copy and standardise EMBER data.
    ember = ember.copy()

    required_ember_columns = {"EMISSION", "YEAR", "VALUE"}
    missing_ember_columns = required_ember_columns.difference(ember.columns)

    if missing_ember_columns:
        raise ValueError(
            "EMBER data is missing required columns: "
            f"{sorted(missing_ember_columns)}"
        )

    ember["EMISSION"] = (
        ember["EMISSION"]
        .astype(str)
        .str.strip()
    )

    ember["YEAR"] = pd.to_numeric(
        ember["YEAR"],
        errors="coerce",
    )

    ember["VALUE"] = pd.to_numeric(
        ember["VALUE"],
        errors="coerce",
    )

    ember = ember.dropna(
        subset=["EMISSION", "YEAR", "VALUE"]
    )

    # Convert the emissions list and model years.
    emissions_list = (
        emissions["VALUE"]
        .astype(str)
        .str.strip()
        .tolist()
    )

    years = get_years(
        start_year,
        end_year,
    )

    # Create the ordered emission-limit dataframe.
    emission_limit_ordered = pd.DataFrame(
        emission_limit,
        columns=[
            "EMISSION",
            "COUNTRY",
            "TYPE",
            "YEAR",
            "VALUE",
        ],
    )

    emission_limit_ordered["EMISSION"] = (
        emission_limit_ordered["EMISSION"]
        .astype(str)
        .str.strip()
    )

    emission_limit_ordered["COUNTRY"] = (
        emission_limit_ordered["COUNTRY"]
        .astype(str)
        .str.strip()
    )

    emission_limit_ordered["TYPE"] = (
        emission_limit_ordered["TYPE"]
        .astype(str)
        .str.strip()
        .str.upper()
    )

    emission_limit_ordered["YEAR"] = pd.to_numeric(
        emission_limit_ordered["YEAR"],
        errors="coerce",
    )

    emission_limit_ordered["VALUE"] = pd.to_numeric(
        emission_limit_ordered["VALUE"],
        errors="coerce",
    )

    if emission_limit_ordered[
        ["EMISSION", "COUNTRY", "TYPE", "YEAR", "VALUE"]
    ].isna().any().any():
        raise ValueError(
            "Emission limits contain missing or invalid values."
        )

    emission_limit_ordered = (
        emission_limit_ordered
        .sort_values(
            by=[
                "EMISSION",
                "COUNTRY",
                "YEAR",
            ]
        )
        .reset_index(drop=True)
    )

    # Create a dataframe template for all emissions and years.
    template = pd.DataFrame(
        itertools.product(
            emissions_list,
            years,
        ),
        columns=[
            "EMISSION",
            "YEAR",
        ],
    )

    template["YEAR"] = pd.to_numeric(
        template["YEAR"],
        errors="coerce",
    )

    # Loop through each emission type that has a specified limit.
    for emission in emission_limit_ordered["EMISSION"].unique():

        emission_limits = emission_limit_ordered.loc[
            emission_limit_ordered["EMISSION"] == emission
        ]

        # Loop only through countries with limits for this emission.
        for country in emission_limits["COUNTRY"].unique():

            prev_data_year = None
            prev_data_value = None

            # Set input limits for the given country and emission.
            limits = emission_limit_ordered.loc[
                (
                    emission_limit_ordered["COUNTRY"] == country
                )
                & (
                    emission_limit_ordered["EMISSION"] == emission
                )
            ].copy()

            # The emissions data uses combined emission-country keys,
            # such as CO2AFG.
            expected_emission_key = (
                f"{emission}{country}"
            ).strip()

            # Filter the template for this country and emission.
            data = template.loc[
                template["EMISSION"] == expected_emission_key
            ].copy()

            data = data.reset_index(drop=True)

            if data.empty:
                raise ValueError(
                    "No matching emissions template data found for "
                    f"emission={emission!r}, country={country!r}, "
                    f"expected key={expected_emission_key!r}"
                )

            # Loop through limits for this country.
            for _, row in limits.iterrows():

                data_type = row["TYPE"]
                data_year = int(row["YEAR"])
                data_value = float(row["VALUE"])

                # If no previous target exists, establish the first
                # baseline or target.
                if prev_data_year is None:

                    # LINEAR limits require historical EMBER data.
                    if data_type == "LINEAR":

                        ember_data = ember.loc[
                            ember["EMISSION"]
                            == expected_emission_key
                        ].copy()

                        # Stop with a useful error instead of producing
                        # an IndexError later.
                        if ember_data.empty:
                            raise ValueError(
                                "No EMBER data found for "
                                f"emission={emission!r}, "
                                f"country={country!r}, "
                                f"expected key="
                                f"{expected_emission_key!r}"
                            )

                        ember_data = (
                            ember_data
                            .sort_values(by="YEAR")
                            .reset_index(drop=True)
                        )

                        model_years = pd.to_numeric(
                            data["YEAR"],
                            errors="coerce",
                        )

                        first_model_year = model_years.min()

                        # Copy EMBER observations that overlap with
                        # the model horizon.
                        overlapping = ember_data.loc[
                            ember_data["YEAR"].isin(model_years)
                        ].copy()

                        for _, ember_row in overlapping.iterrows():
                            data.loc[
                                data["YEAR"]
                                == ember_row["YEAR"],
                                "VALUE",
                            ] = ember_row["VALUE"]

                        # Select EMBER observations before the model
                        # horizon.
                        prior_data = ember_data.loc[
                            ember_data["YEAR"] < first_model_year
                        ].copy()

                        # If all EMBER data predates the model horizon,
                        # use the most recent historical value as the
                        # interpolation baseline.
                        if overlapping.empty and not prior_data.empty:

                            baseline = (
                                prior_data
                                .sort_values(by="YEAR")
                                .iloc[-1]
                            )

                            baseline_row = pd.DataFrame(
                                [
                                    {
                                        "EMISSION": (
                                            data["EMISSION"].iloc[0]
                                        ),
                                        "YEAR": baseline["YEAR"],
                                        "VALUE": baseline["VALUE"],
                                    }
                                ]
                            )

                            data = pd.concat(
                                [
                                    data,
                                    baseline_row,
                                ],
                                ignore_index=True,
                            )

                            data = (
                                data
                                .sort_values(by="YEAR")
                                .reset_index(drop=True)
                            )

                        # If EMBER has valid data but none of it is
                        # before or inside the model horizon, report
                        # the issue clearly.
                        if overlapping.empty and prior_data.empty:
                            earliest_ember_year = (
                                ember_data["YEAR"].min()
                            )

                            raise ValueError(
                                "EMBER data exists for "
                                f"{expected_emission_key!r}, but the "
                                "earliest EMBER year is after the "
                                f"model horizon starts. "
                                f"Earliest EMBER year: "
                                f"{earliest_ember_year}; "
                                f"model start year: "
                                f"{first_model_year}"
                            )

                    # Set the first target value. This applies to both
                    # LINEAR and POINT limits.
                    data.loc[
                        data["YEAR"] == data_year,
                        "VALUE",
                    ] = data_value

                else:
                    # For a LINEAR target, set only the target point.
                    # The interpolation step below fills values between
                    # the historical baseline and the target.
                    if data_type == "LINEAR":

                        data.loc[
                            data["YEAR"] == data_year,
                            "VALUE",
                        ] = data_value

                    # For a POINT target, hold the previous value until
                    # the current target year, then set the new value.
                    elif data_type == "POINT":

                        data.loc[
                            data["YEAR"].between(
                                prev_data_year,
                                data_year,
                            ),
                            "VALUE",
                        ] = prev_data_value

                        data.loc[
                            data["YEAR"] == data_year,
                            "VALUE",
                        ] = data_value

                    else:
                        raise ValueError(
                            "Unknown emission-limit type "
                            f"{data_type!r} for "
                            f"emission={emission!r}, "
                            f"country={country!r}. "
                            "Expected 'LINEAR' or 'POINT'."
                        )

                # Store the current target for the next iteration.
                prev_data_year = data_year
                prev_data_value = data_value

            # Interpolate values between known LINEAR points.
            data["VALUE"] = (
                data["VALUE"]
                .interpolate(
                    method="linear",
                    limit_direction="both",
                )
            )

            # Remove rows that still have no value.
            data = data.dropna(
                subset=["VALUE"]
            ).copy()

            # Add region and restrict to the model horizon.
            data["REGION"] = region_name

            data = data.loc[
                data["YEAR"].between(
                    start_year,
                    end_year,
                )
            ].copy()

            # Format columns.
            data = data[
                [
                    "REGION",
                    "EMISSION",
                    "YEAR",
                    "VALUE",
                ]
            ]

            # Append data to the final dataframe.
            annual_emission_limit = pd.concat(
                [
                    annual_emission_limit,
                    data,
                ],
                ignore_index=True,
            )

    return annual_emission_limit