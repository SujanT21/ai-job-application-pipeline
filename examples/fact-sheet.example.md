# Fact sheet: Alex Morgan (FICTIONAL example candidate)

The single source of truth for every CV and cover-letter claim. The writer may only use what is here;
the fact-checker vetoes anything that isn't. Replace this file with your own (and keep the real one out of git).

## 1. Fixed facts

| Employer | Title (exact) | Dates |
|---|---|---|
| Northwind Health | Data Analyst | Jan 2024 - Present |
| Contoso Logistics | Junior Data Analyst | Jun 2021 - Dec 2023 |

- Experience wording: "over four years" (never "4+", never "5 years").
- Education: MSc Data Science, Example University, 2020-2021.
- Visa line (cover letters and forms only, never on the CV):
  "My current visa runs until <date>, and I will require Skilled Worker sponsorship."

## 2. Skills inventory

| Skill | Level | Where |
|---|---|---|
| SQL | core | both roles |
| Python (pandas, scikit-learn) | core | Northwind |
| dbt, Snowflake | core | Northwind |
| Power BI, DAX | core | Contoso |
| A/B test design | used | Contoso only |

**NOT HELD - never claim, even if the advert asks:** Java, Spark, Databricks, Tableau, Airflow pipelines,
line management, "deployed to production" machine learning.

## 3. Approved numbers

| Metric | Allowed wording | Forbidden variants |
|---|---|---|
| dbt models | "30 documented dbt models with 150+ automated tests" | "30 tested models" |
| Dashboard fix | "corrected a KPI overstated by about 12 points" | "fixed all KPIs" |
| Churn model | "ROC-AUC 0.84 on a later held-out period" | "0.84 ROC-AUC" without the period; "deployed" |

## 4. Evidence bank (bullet library)

- NW-1: Built 30 documented dbt models in Snowflake with 150+ automated tests.
- NW-2: Corrected a readmissions KPI overstated by about 12 points by fixing a join in the core model.
- NW-3: Built a churn model in Python with ROC-AUC 0.84 on a later held-out period.
- CL-1: Designed A/B tests for warehouse pick-route changes.
- CL-2: Built Power BI dashboards with DAX for delivery performance.
