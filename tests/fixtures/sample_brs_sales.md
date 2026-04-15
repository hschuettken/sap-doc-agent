# Sales Analytics Dashboard - BRS

**Document Version:** 1.2  
**Business Domain:** Sales & Distribution  
**Status:** Draft for Review  
**Author:** Sales Controlling Team  
**Date:** 2026-01-15

---

## 1. Business Background

The Sales Controlling team requires a self-service analytics dashboard providing real-time visibility into sales performance across all sales organisations and distribution channels. Currently, reporting is produced manually from SAP ECC exports in Excel, causing delays and inconsistencies.

The target solution must be implemented on SAP Analytics Cloud (SAC) with the data model hosted in SAP Datasphere (DSP).

---

## 2. Business Entities

### 2.1 Primary Entities

| Entity | Type | Description | Source Table |
|---|---|---|---|
| Sales Order | Fact | Header-level sales documents | VBAK |
| Sales Order Item | Fact | Line-item detail per sales order | VBAP |
| Customer | Dimension | Sold-to and ship-to parties | KNA1 |
| Product / Material | Dimension | Materials and product groups | MARA, MARC |
| Sales Organisation | Dimension | Org-unit hierarchy (SalesOrg / DivCh / Division) | TVKO, T001W |
| Distribution Channel | Dimension | 10, 20, 30 (Retail, Wholesale, Direct) | TVTW |

### 2.2 Entity Relationships

- Sales Order Item (VBAP) → Sales Order (VBAK) via VBELN
- Sales Order Item → Customer (KNA1) via KUNAG (sold-to)
- Sales Order Item → Material (MARA) via MATNR
- Sales Order Item → Sales Organisation (TVKO) via VKORG/VTWEG/SPART

---

## 3. Measures and KPIs

### 3.1 Base Measures

| Measure | Description | Aggregation | Unit |
|---|---|---|---|
| Net Revenue | Net value after discounts (NETWR) | SUM | Document currency |
| Gross Margin | Revenue minus COGS | SUM | Document currency |
| Order Quantity | Ordered quantity in base UoM (KWMENG) | SUM | Base UoM |
| Returns Quantity | Returns per return order type (RE) | SUM | Base UoM |
| Number of Orders | Distinct sales orders | COUNT DISTINCT | - |

### 3.2 Calculated Measures

| Measure | Formula | Description |
|---|---|---|
| Returns Rate | Returns Quantity / Order Quantity | Percentage of volume returned |
| Average Order Value | Net Revenue / Number of Orders | Mean order size |
| Gross Margin % | Gross Margin / Net Revenue | Margin as percentage |

### 3.3 KPIs

| KPI | Definition | Target | Frequency |
|---|---|---|---|
| Revenue Growth YoY | (Current Period Revenue - Prior Year Revenue) / Prior Year Revenue | +5% YoY | Monthly |
| Customer Acquisition Cost | Marketing Spend / New Customers Acquired | < EUR 250 | Quarterly |
| Margin by Product Group | Gross Margin % grouped by MATKL | > 35% | Monthly |
| Top 10 Customers by Revenue | Ranking of customers by Net Revenue | N/A — informational | Monthly |
| Returns Rate by Material | Returns Rate per MATNR | < 2% | Weekly |

---

## 4. Grain and Dimensionality

### 4.1 Primary Grain

The primary reporting grain is **Sales Order Item level** (one row per VBAP line item). This enables drill-down from summary to individual order lines.

**NOTE — Conflicting Requirement:** Section 6.2 of this document specifies a requirement for a "customer-day" aggregated view for trend analysis, which implies a different grain (Customer × Calendar Day). This conflict must be resolved before build begins.

### 4.2 Dimensions

- Calendar Date (posting date BUDAT)
- Sales Organisation (VKORG)
- Distribution Channel (VTWEG)
- Division (SPART)
- Customer (sold-to KUNAG)
- Material (MATNR)
- Material Group (MATKL)
- Document Type (AUART)
- Plant (WERKS)

---

## 5. Time Semantics

### 5.1 Time Type

Event-based fact table (each row represents a posted sales order item).

### 5.2 Comparison Periods

- Month-over-Month (MoM)
- Year-over-Year (YoY) — calendar year
- Fiscal Year-over-Year — fiscal year variant V3 (April start)
- Rolling 12 months (R12)
- Quarter-to-Date (QTD) and Year-to-Date (YTD)

### 5.3 Fiscal Year

Fiscal year variant: **V3** (April–March). Fiscal periods must be aligned with the Group FY calendar. Both calendar and fiscal year views required simultaneously.

---

## 6. Additional Requirements

### 6.1 Active Customer Definition

The dashboard must show metrics for "active customers" only. **Ambiguity: the term "active customer" is not defined in this document.** Possible interpretations include:
- Customers with at least one order in the last 12 months
- Customers with KUNNR status = 'A' in KNA1
- Customers with credit limit > 0

Business owner must confirm the definition before the data model is finalised.

### 6.2 Customer-Day Aggregation View

For trend sparklines, the dashboard requires a pre-aggregated view at **Customer × Calendar Day** grain showing Net Revenue and Order Count. This conflicts with the item-level grain stated in Section 4.1.

---

## 7. Source Systems

| System | Type | Version | Tables |
|---|---|---|---|
| SAP ECC 6.0 EhP8 | ERP | 7.52 | VBAK, VBAP, KNA1, MARA, MARC, KONV |
| SAP BW/4HANA | Data warehouse | 2.0 SP08 | 0SD_C03 (existing InfoCube) |

Replication via SAP Data Services or CDS Views + SLT replication flow.

---

## 8. Security Requirements

- Row-level security: Users may only see data for their assigned Sales Organisation(s)
- Column-level security: Gross Margin and COGS data restricted to Finance role
- Roles: SD_ANALYST (read-all), SD_MANAGER (read + export), SD_CONTROLLER (full including margins)

---

## 9. Non-Functional Requirements

| Category | Requirement |
|---|---|
| Volume | ~2 million order line items per year; ~10 million rows in initial load (3-year history) |
| Query performance | Interactive queries < 5 seconds at P95 |
| Refresh frequency | Daily batch load at 06:00 CET |
| Availability | 99.5% during business hours (07:00–20:00 CET) |
| Data retention | 5 years rolling |

---

## 10. Open Questions

1. Confirm definition of "active customer" (see Section 6.1)
2. Resolve grain conflict between Section 4.1 (item-level) and Section 6.2 (customer-day)
3. Is the existing BW InfoCube 0SD_C03 to be decommissioned post-migration or kept in parallel?
4. COGS source: is standard price (STPRS) acceptable, or do we need actual costs from CO-PA?
5. Multi-currency reporting: report in document currency or a single group currency (EUR)?

---

*End of Document*
