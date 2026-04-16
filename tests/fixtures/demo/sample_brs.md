# Sales Planning — Business Requirements Specification

## Executive Summary
Revenue reporting dashboard for regional sales teams with drill-down from geography to product level.

## KPI Definitions
- **Net Revenue**: Gross sales minus discounts and returns
- **Gross Margin**: (Net Revenue - COGS) / Net Revenue
- **YTD Growth**: Year-to-date revenue vs prior year

## Data Sources
- SAP S/4HANA: Sales orders (VBAK/VBAP)
- SAP BW: Existing revenue cube (0SD_C01)

## Dimensions
- Time (Year, Quarter, Month, Week)
- Product (Category, Subcategory, Material)
- Geography (Region, Country, City)
- Sales Organization

## Requirements
1. Executive overview page with KPI tiles and trend charts
2. Regional drill-down with variance analysis
3. Product performance ranking with waterfall
4. Monthly actuals vs plan comparison
