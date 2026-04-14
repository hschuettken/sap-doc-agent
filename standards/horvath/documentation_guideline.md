# Horvath SAP Documentation Guideline
## BW/4HANA and Datasphere Projects

**Version:** 1.0
**Status:** Active
**Applies to:** All Horvath-led SAP BW/4HANA and SAP Datasphere engagements
**Maintained by:** Horvath Center of Excellence — Data & Analytics

---

## Table of Contents

1. [Purpose and Audience](#1-purpose-and-audience)
2. [Document Types and When to Write Them](#2-document-types-and-when-to-write-them)
3. [Structure and Templates](#3-structure-and-templates)
4. [Writing Style Rules](#4-writing-style-rules)
5. [Naming and Cross-Referencing](#5-naming-and-cross-referencing)
6. [Quality Criteria](#6-quality-criteria)
7. [Maintenance and Review Cycle](#7-maintenance-and-review-cycle)
8. [Common Documentation Anti-Patterns](#8-common-documentation-anti-patterns)
9. [Tools and Formats](#9-tools-and-formats)

---

## 1. Purpose and Audience

### Why Documentation Matters in SAP Projects

SAP BW/4HANA and Datasphere implementations are long-lived. The consultants who build a data model are rarely the people who operate it two years later, and the business analysts who define the reporting requirements are rarely the ones who debug a broken process chain at 07:00 on a Monday. Documentation is the connective tissue between intent and execution.

Without adequate documentation:

- A junior developer cannot determine whether a missing record is a bug or a design decision.
- An auditor cannot trace a KPI back to its source system without reverse-engineering the transformation chain.
- A business owner cannot verify that a new SAP release has not changed the semantics of a calculation.
- Onboarding a replacement consultant takes weeks instead of days.

This guideline defines Horvath's standard for what documentation must exist, what it must contain, and how it must be written. It is not aspirational. These requirements apply to every production-bound deliverable.

### Who Reads What

Understanding the audience for each document type determines the appropriate level of technical detail. Write for the person who needs it, not for the person who writes it.

| Reader | Primary Concerns | Document Types They Rely On |
|---|---|---|
| **Business Analyst** | Does the system answer the right question? Are the business rules correct? | BRS, Architecture Overview (layer/system summary), Data Flow |
| **Developer** | How is this built? What are the rules I must follow? What feeds this object? | Development Guidelines, Object Documentation, Data Flow |
| **Operations / Support** | Why did this fail? What do I do now? Who do I call? | Operational Runbook, Data Flow (error handling sections) |
| **Business Owner** | Is my data accurate? When was this last changed? Who approved it? | BRS (sign-off, acceptance criteria), Master Data Documentation |
| **Auditor** | Where does this number come from? Who changed this and when? Can I trace it? | Architecture Overview, BRS, Data Flow, Object Documentation |
| **Onboarding Consultant** | How is this landscape organized? What conventions must I follow? | Architecture Overview, Development Guidelines |

A document that serves all audiences simultaneously serves none. The Architecture Overview addresses the auditor and the onboarding consultant. The Operational Runbook addresses operations. Choose your primary reader and write to them, then add an executive summary for the others.

---

## 2. Document Types and When to Write Them

The following seven document types form the complete Horvath documentation set. They are not independent — they reference each other and together describe the complete system.

One document can cover multiple sections if the scope is narrow enough. A small data flow might combine the BRS, Data Flow, and Object Documentation into a single coherent page. What matters is that all required content is present, not that it is fragmented across seven separate files.

### 2.1 Architecture Overview

**Scope:** System level. One per landscape (one for BW/4HANA, one for Datasphere, or one combined if both serve the same domain).

**Write it:** At project kick-off, before any objects are built. Update it whenever a new source system, layer, or integration point is added.

**Primary audience:** Onboarding consultants, architects, auditors.

**It must exist** before a project goes live. No exceptions.

### 2.2 Development Guidelines

**Scope:** Project or space level. One per development environment (one for the BW system, one per Datasphere space with independent governance).

**Write it:** At project start, reviewed and confirmed before the first developer writes a line of code. Update it whenever a naming convention is extended or a process rule changes.

**Primary audience:** Developers, technical leads, code reviewers.

### 2.3 Business Requirements Specification (BRS)

**Scope:** Data flow or use case level. One BRS per logical reporting area or business process (e.g., one for Profitability Analysis, one for Inventory Ageing, one for Headcount Reporting).

**Write it:** Before development begins, authored with the business owner. It is the contract between business and IT. If it does not exist before objects are built, write it retroactively and have it signed off.

**Primary audience:** Business owner, business analyst, auditor.

### 2.4 Data Flow Documentation

**Scope:** Pipeline level. One per data pipeline or process chain (e.g., one for the nightly GL extraction, one for the DSP view chain serving the profitability mart).

**Write it:** When the pipeline is designed. Update it whenever the source, transformation logic, target, or schedule changes.

**Primary audience:** Developers, operations, auditors.

### 2.5 Object Documentation

**Scope:** Object level. Required for every significant object: Advanced DSO, Composite Provider, Analytic View, Calculation View, DTO, table function, replication flow target table.

**"Significant"** means: any object that is directly consumed by a report, exposed via an API, shared across use cases, or contains business logic. Simple staging DSOs that are pure 1:1 extracts with no transformation may reference their Data Flow document instead of having a standalone Object Documentation.

**Write it:** When the object is created. Update it on every structural change.

**Primary audience:** Developers, operations.

### 2.6 Master Data Documentation

**Scope:** Domain level. One per master data domain (e.g., one for Cost Center hierarchy, one for Material Classification, one for Customer segmentation).

**Write it:** When master data governance is established. Update it when hierarchy levels or attribute semantics change.

**Primary audience:** Business owner, data steward, developer.

### 2.7 Operational Runbook

**Scope:** Process chain or task chain level. One per production job or set of interdependent jobs that operations monitors together.

**Write it:** Before go-live, authored with input from the team that will operate the system post-go-live. It is not complete until someone from operations has read it and confirmed they could use it without asking the project team for help.

**Primary audience:** Operations, support team.

---

## 3. Structure and Templates

The templates below define what each document must contain. Sections marked **[Required]** must be present and substantive. Sections marked **[Conditional]** are required when the stated condition applies.

### 3.1 Architecture Overview Template

```
# Architecture Overview — [System Name / Domain]

## Document Control
Author: [Name] | Version: [x.y] | Last Updated: [YYYY-MM-DD] | Status: [Draft/Active]

## 1. System Landscape [Required]
Describe every system involved: source systems (ERP, CRM, flat files), BW/4HANA or
Datasphere, SAC, external consumers. Include connection type (SDA, replication flow,
BW source system connection) and data direction.

Example:
> S/4HANA (ERP) — BW source system connection → BW/4HANA (modelling + mart) →
> SAP Analytics Cloud (reporting). A secondary flat-file feed arrives via SFTP and
> is staged in DSP before handoff to BW via a Replication Flow.

## 2. Data Flow Map [Required — diagram mandatory]
A diagram showing the end-to-end data path from source to report.
Minimum: source boxes, layer boxes (RAW / HARMONIZED / MART / CONSUMPTION),
consumer boxes, arrows with labels (technology + frequency).

## 3. Layer Architecture [Required]
For each layer, define: what it contains, what transformation is permitted,
persistence strategy (in-memory vs. persisted), and naming prefix.

Example:
> RAW layer (prefix: R_): Contains 1:1 replicas of source data with no
> business transformation. Fields use technical names from the source. No
> calculated measures. Retention: 13 months rolling.

## 4. Space / Package Organization [Required]
How spaces (DSP) or packages/InfoAreas (BW) are organized. Include ownership
and what may not be mixed (e.g., "staging objects must never reside in the
MART space").

## 5. Integration Points [Required]
Every external connection: other SAP systems, APIs, file transfers, SAC tenants.
For each: direction, protocol, owner, failure behavior.

## 6. Security and Authorization [Required]
Which roles exist, what data they can access, how row-level security is
implemented, and who governs role assignment.
```

### 3.2 Development Guidelines Template

```
# Development Guidelines — [Project / Space Name]

## Document Control
Author: [Name] | Version: [x.y] | Last Updated: [YYYY-MM-DD]

## 1. Naming Conventions [Required]
One table per object type. Include prefix, example, and what the prefix means.

| Object Type | Prefix | Example | Notes |
|---|---|---|---|
| DSO (RAW) | R_ | R_FI_GL_LINE_ITEMS | No transformations |
| DSO (HARMONIZED) | H_ | H_FI_COST_CENTER | Currency-converted |
| Composite Provider | CP_ | CP_FI_MARGIN_ANALYSIS | — |

Counter-example (how NOT to name):
> X_TEMP_FI_TEST_2 — No layer indication, no business domain, throwaway suffix

## 2. Coding Standards [Required]
ABAP and SQL rules with explicit examples.

Example rule:
> SELECT statements must always specify a WHERE clause. Full-table reads on
> fact DSOs are prohibited without documented exception. Reason: BW fact tables
> with 100M+ rows will cause runtime failures in dialog processes.

## 3. Layer Architecture Rules [Required]
What may and may not happen in each layer. Be specific about joins,
aggregations, currency conversion, and calculated measures.

## 4. Transport and Deployment Process [Required]
Step-by-step: how a change moves from development to test to production.
Include who approves each step and what must be tested before promoting.

## 5. Testing Requirements [Required]
What tests are mandatory. Minimum: row count reconciliation against source,
spot-check of calculated measures against manual calculation, empty-source
handling test.

## 6. Code Review Checklist [Required]
A checklist that reviewers complete before approving a transport.

## 7. Reuse and Shared Objects [Required]
When to create a shared object vs. a local copy. Which objects are governed
centrally (master data DSOs, shared helper views) and may not be modified
without architecture approval.
```

### 3.3 Business Requirements Specification Template

```
# Business Requirements Specification — [Use Case Name]

## Document Control
Author: [Name] | Business Owner: [Name] | Version: [x.y]
Last Updated: [YYYY-MM-DD] | Status: [Draft / Under Review / Approved]

## 1. Business Objective [Required]
One paragraph. Why does this exist? What decision does it support?

Example:
> The Profitability Analysis report enables the Controlling team to compare
> actual contribution margins against plan values at the product-group level
> by month and company code. It replaces the current Excel-based process
> which requires three working days to compile and is error-prone due to
> manual currency conversion.

## 2. Data Scope [Required]
What data. What time range. What granularity. What entities are in scope
and explicitly what is out of scope.

## 3. Business Rules and Calculations [Required]
Every formula, aggregation rule, currency conversion, and allocation method.
Write these in business language first, then add the technical expression.

Example:
> Contribution Margin I = Net Revenue minus Cost of Goods Sold.
> Net Revenue excludes inter-company postings (partner company code populated).
> Currency conversion uses the average rate of the posting period, stored in
> InfoObject 0RTYPE with value 'M'. Plan values use the fixed budget rate
> (0RTYPE = 'P').

## 4. Source Systems [Required]
Where the data originates. Extraction method. Frequency. Known data quality issues.

## 5. Output and Consumers [Required]
Who uses this data. Which SAC story or report. What format (table, chart, export).
Expected user count and query frequency (informs performance requirements).

## 6. Acceptance Criteria [Required]
How correctness is verified. Reconciliation targets. Known tolerances.

Example:
> Total net revenue in BW must reconcile within 0.1% of the S/4HANA
> financial closing report (transaction F.01) for the same period and company code.
> Deviations above 0.1% block production sign-off.

## 7. Sign-off [Required]
| Role | Name | Date | Signature |
|---|---|---|---|
| Business Owner | | | |
| Project Lead | | | |
| Data Architect | | | |

## 8. Change History
| Version | Date | Author | Change |
|---|---|---|---|
```

### 3.4 Data Flow Documentation Template

```
# Data Flow — [Flow Name]

## Document Control
Author: [Name] | Version: [x.y] | Last Updated: [YYYY-MM-DD]
Related BRS: [link] | Related Objects: [link, link]

## 1. Source to Target Overview [Required — diagram mandatory]
A diagram or structured table showing every hop in the chain:
Source Object → Transformation Step → Target Object

Example (table form when a diagram is not yet available):
| Step | From | Type | To | Technology |
|---|---|---|---|---|
| 1 | S/4HANA ACDOCA | Replication Flow | R_FI_GL_ITEMS (DSO) | DSP Replication Flow |
| 2 | R_FI_GL_ITEMS | Data Flow | H_FI_GL_ITEMS (DSO) | BW Transformation |
| 3 | H_FI_GL_ITEMS | Data Flow | CP_FI_MARGIN | Composite Provider |

## 2. Transformation Logic [Required]
For every transformation step: what happens to the data and why.
This is the most important section. Do not write "see ABAP routine Z_WHATEVER".
Write what the routine does in business terms and reference the code only as
a pointer for those who need the implementation detail.

Example:
> Step 2 applies three transformations:
> 1. Currency conversion: all amounts in local currency (field DMBTR) are
>    converted to EUR using the monthly average rate. The rate source is the
>    BW currency table maintained centrally by Finance Controlling.
> 2. Inter-company elimination: records where RASSC (partner company code)
>    is populated are flagged with IC_FLAG = 'X' and excluded from external
>    reporting aggregates but retained in the DSO for internal reconciliation.
> 3. Cost element mapping: the source cost element (KSTAR) is mapped to the
>    Horvath reporting category using the mapping table T_CE_MAPPING,
>    maintained by the Cost Accounting team.

## 3. Filter and Selection Criteria [Required]
What data is included. What is explicitly excluded. Date range logic.

## 4. Error Handling [Required]
What happens when: the source is empty, a record fails validation, currency
rates are missing, a duplicate key is detected. Who is notified and how.

## 5. Schedule and Frequency [Required]
When does this run? What triggers it? What is the SLA (data must be available by X)?

## 6. Dependencies [Required]
What must complete before this flow runs. What flows depend on this one completing.
```

### 3.5 Object Documentation Template

```
# Object: [Technical Name] — [Business Name]

## Document Control
Author: [Name] | Version: [x.y] | Last Updated: [YYYY-MM-DD]
Layer: [RAW / HARMONIZED / MART / CONSUMPTION]
Space / Package: [Name]

## 1. Business Purpose [Required]
One to three sentences. What question does this object help answer?

## 2. Owner and Responsible Team [Required]
Technical owner (team responsible for correctness) and business owner
(team responsible for content governance).

## 3. Key Fields and Business Meaning [Required]
Do not list all fields — document the fields that carry business meaning
or that are non-obvious.

| Field | Technical Name | Business Meaning | Example Values |
|---|---|---|---|
| Posting Date | BUDAT | The date the business transaction was recorded in FI | 2024-01-31 |
| Reporting Category | Z_REPCAT | Maps cost elements to P&L line items per Horvath chart of accounts | COGS, OPEX, R&D |

## 4. Data Volume and Retention [Required]
Current row count (approximate). Expected annual growth. Retention policy.

## 5. Layer Assignment [Required]
Which layer and a one-sentence justification.

## 6. Upstream Dependencies [Required]
What feeds this object. Reference the Data Flow document.

## 7. Downstream Consumers [Required]
What reads this object. Include Composite Providers, views, process chains,
and external consumers (SAC stories, APIs).
```

### 3.6 Master Data Documentation Template

```
# Master Data — [Domain Name]

## Document Control
Author: [Name] | Data Steward: [Name] | Version: [x.y] | Last Updated: [YYYY-MM-DD]

## 1. Hierarchy Structure [Required — diagram recommended]
The complete hierarchy: how many levels, what each level represents,
how leaf nodes are defined, whether the hierarchy is time-dependent.

## 2. Attributes and What They Control [Required]
| Attribute | Technical Name | Values | Business Effect |
|---|---|---|---|
| Controlling Area | KOKRS | 1000, 2000 | Partitions cost center reporting |
| Hierarchy Version | HIERVER | ACT (Actual), PLAN | Plan vs. actuals use different hierarchies |

## 3. Maintenance Responsibility [Required]
Who creates values. Who can change them. What approval is needed before
a new value goes to production. What happens if a value is retired.

## 4. Cross-System Mapping [Required]
How values in this master data object map to other systems. Include
mapping tables if they exist in the system.
```

### 3.7 Operational Runbook Template

```
# Operational Runbook — [Process Chain / Area Name]

## Document Control
Author: [Name] | Operations Contact: [Name] | Version: [x.y]
Last Updated: [YYYY-MM-DD] | SLA: [data available by HH:MM local time]

## 1. Daily and Weekly Checks [Required]
What to check. Where to look. What is normal. What is abnormal.

Example:
> Check the BW Job Overview (transaction SM37) for jobs starting with
> ZMONTH_FI_*. All jobs must show status FINISHED by 06:00 CET.
> Expected runtime: 45-75 minutes. A runtime exceeding 90 minutes
> indicates a table lock — proceed to Known Issues section 2.

## 2. Known Issues and Workarounds [Required]
| Symptom | Probable Cause | Resolution | Escalate If |
|---|---|---|---|
| Job Z_FI_LOAD aborts with "no authorization" | Batch user password expired | Reset service user password per IT process #1234 | Reset fails or recurs within 7 days |

## 3. Escalation Contacts [Required]
| Tier | When | Contact | How |
|---|---|---|---|
| L1 Operations | First response, job restarts | [Name / queue] | ServiceNow ticket |
| L2 BW Developer | Data issues, transformation bugs | [Name] | Phone + ticket |
| L3 Horvath CoE | Architecture decisions, major failures | [Name] | Phone |

## 4. Recovery Procedures [Required]
Step-by-step instructions for the most common failure scenarios.
Each procedure must state: precondition check, steps, verification,
and how long recovery is expected to take.

Example:
> Procedure: Reprocess a failed delta load
> 1. Verify the source delta queue is intact (RSA7 in S/4HANA).
> 2. In BW, delete the failed request from the target DSO (manage DSO,
>    delete request — do NOT use selective deletion).
> 3. Restart the InfoPackage from the Process Chain monitor.
> 4. Verify row count in target DSO matches the number of records in the
>    source delta queue. Tolerance: 0 (delta must be exact).
> Expected duration: 30-45 minutes for loads up to 500K records.
```

---

## 4. Writing Style Rules

### Business Language First, Technical Detail Second

Every document section opens with a business-language explanation before introducing technical names. The reader who needs the business context should not have to wade through InfoObject names to understand what the system does.

Wrong:
> ZFIC_MARGIN_A uses 0AMOUNT with RTYPE M to calculate the 0KSTAR allocation.

Correct:
> The contribution margin calculation converts all amounts to EUR using the monthly average exchange rate, then allocates cost elements to reporting categories. The technical implementation uses InfoObject 0AMOUNT (currency amount), exchange rate type M (monthly average), and InfoObject 0KSTAR (cost element).

### Active Voice, Present Tense

Write what the system does, not what it was designed to do.

Wrong: "The transformation was designed to convert amounts."
Correct: "The transformation converts amounts to EUR."

### Diagrams Are Required for Architecture and Data Flows

Every Architecture Overview must include a system landscape diagram and a data flow diagram. Every Data Flow document must include a source-to-target flow diagram. These are not optional.

Diagrams must be embedded in the document or linked directly. A note saying "diagram available on request" does not meet this requirement.

### Field Descriptions Must Explain Business Meaning

A field description that restates the technical name adds no value.

Wrong: "BUDAT — Posting Date. This field contains the posting date."
Correct: "BUDAT — Posting Date. The date the business transaction was recorded in the general ledger. This controls period assignment for financial closing. It differs from the document date (BLDAT), which is when the original business event occurred."

### Why Before What

Every transformation rule must include a business reason. Without the reason, the next developer cannot evaluate whether a change breaks the intent.

Wrong: "Records where RASSC is populated are excluded."
Correct: "Records where RASSC (partner company code) is populated represent inter-company transactions. These are excluded from external reporting to avoid double-counting revenue and costs that net to zero at group level. They are retained in the DSO for internal reconciliation against the inter-company elimination report."

---

## 5. Naming and Cross-Referencing

### Document Naming Convention

All documents follow the pattern:

```
[DocumentType]_[Domain]_[Subject]_v[Major].[Minor]
```

Examples:
- `ARCHv1.0_FI_FinancialReporting` — Architecture Overview for Financial Reporting, version 1.0
- `BRS_v1.2_FI_ProfitabilityAnalysis` — Business Requirements Specification
- `FLOW_v2.0_FI_GL_DeltaLoad` — Data Flow documentation
- `OBJ_v1.0_H_FI_GL_LINE_ITEMS` — Object Documentation

On wiki platforms (BookStack, Confluence), use the document type as the page prefix. Keep versions in the document header, not in the page title — the platform manages history.

### Linking Between Related Documents

Every document must link to its related documents in both directions.

| Document | Must Link To |
|---|---|
| BRS | Related Data Flow(s), Architecture Overview |
| Data Flow | Related BRS, all Object Documentation for objects in the chain |
| Object Documentation | Data Flow that creates it, downstream consumers (link to their Object Docs or the consuming report) |
| Architecture Overview | All BRS documents for flows within scope |
| Operational Runbook | All Data Flow documents for processes covered |

Links must use the platform's native link mechanism (not copy-pasted URLs that break on rename). On BookStack: use `@[page-name]` references. On Confluence: use `//` inline links.

### Version Numbering

- **Major version** (x.0): Document structure changes, significant content additions, business rule changes.
- **Minor version** (x.y): Corrections, clarifications, minor additions that do not change meaning.

The change history table in every document records every version, who changed it, and what changed. "Editorial corrections" is not an acceptable change description — state what was corrected and why it was wrong.

---

## 6. Quality Criteria

### Complete

A complete document contains all required sections with substantive content. "Substantive" means the section would allow the primary audience to act on it without asking the author for clarification.

### Adequate

An adequate document is missing no required section, but one or more sections are thin — they state facts without context, or list items without explanation. Adequate is the minimum acceptable for go-live. Complete is the target.

### Insufficient

A document is insufficient if any required section is missing, if a section exists but contains only placeholders, or if critical cross-references are broken. Insufficient documentation blocks go-live.

### Minimum Content Requirements

These lengths are minimums, not targets. A transformation with three business rules cannot be documented in 50 words.

| Document Type | Section | Minimum |
|---|---|---|
| Architecture Overview | System Landscape | 200 words |
| Architecture Overview | Layer Architecture | 200 words |
| BRS | Business Objective | 100 words |
| BRS | Business Rules | 100 words |
| Data Flow | Transformation Logic | 200 words |
| Object Documentation | Key Fields | 100 words, minimum 3 fields documented |
| Operational Runbook | Recovery Procedures | 100 words, minimum 1 full procedure |

### Required Visual Elements

| Document Type | Required Visuals |
|---|---|
| Architecture Overview | System landscape diagram, data flow map |
| Data Flow | Source-to-target flow diagram |
| Master Data | Hierarchy diagram (if hierarchy has more than 2 levels) |

### Completeness Checklist by Document Type

**Architecture Overview — Complete when:**
- [ ] All source systems named with connection type
- [ ] All layers defined with naming convention and permitted content
- [ ] System landscape diagram present and current
- [ ] Data flow diagram present and current
- [ ] Security concept describes at minimum: roles, row-level security approach, governance

**BRS — Complete when:**
- [ ] Business owner identified by name
- [ ] Acceptance criteria include a measurable reconciliation target
- [ ] All business rules have a stated reason, not just a formula
- [ ] Sign-off table populated with at least business owner and project lead

**Data Flow — Complete when:**
- [ ] Every hop in the chain is documented (no gaps between source and target)
- [ ] Transformation logic uses business language for every step
- [ ] Error handling states what happens for empty source, duplicate key, and missing reference data
- [ ] Schedule includes SLA (not just frequency)

**Object Documentation — Complete when:**
- [ ] All non-obvious fields are documented with business meaning
- [ ] Upstream and downstream are both linked, not just named
- [ ] Data volume estimate is present

**Operational Runbook — Complete when:**
- [ ] A member of the operations team has reviewed it and confirmed usability
- [ ] Every known failure scenario has a documented recovery procedure
- [ ] Escalation contacts are current and include phone numbers for P1 issues

---

## 7. Maintenance and Review Cycle

### When to Update

Documentation must be updated before or simultaneously with the corresponding system change going to production. A transport that introduces a new calculation rule cannot be approved for production if the BRS and Data Flow documentation have not been updated.

Mandatory update triggers:

- Any structural change to a documented object (new field, changed key, removed field)
- Any new object that is consumed by an existing documented flow
- Any change to a business rule, filter criterion, or calculation
- Any change to the load schedule or SLA
- Addition of a new source system or consumer
- Any change to the authorization concept

Additionally, all documentation undergoes a quarterly review regardless of system changes. The purpose of the quarterly review is to verify that the documentation matches what is actually running in production.

### Review Responsibilities

| Role | Responsibility |
|---|---|
| **Author** | Produces the first version. Responsible for technical accuracy. Updates on system change. |
| **Peer Reviewer** | Another developer or consultant on the project. Reviews for technical accuracy, completeness, and clarity. Required before a document is marked Active. |
| **Business Owner** | Reviews and signs off on BRS documents. Confirms that business rules are correctly captured. Must re-sign if business rules change. |
| **Horvath CoE** | Reviews Architecture Overviews and Development Guidelines before they are distributed to the customer team. Signs off on initial versions. |

Peer review is not optional. A document written by one person and read by no one before publishing does not meet this standard.

### Handling Outdated Documentation

When a document is discovered to be out of date:

1. Mark the document status as **Needs Update** immediately. Do not leave a document that is known to be wrong marked as Active.
2. Create a task for the responsible author to update it. Define the deadline — for anything that affects production operations, the maximum is five business days.
3. If the author is no longer available, the project lead assigns a new owner.

Documents that are more than 90 days past their last review without a confirmed status are automatically flagged for review. The responsible team lead is notified.

Do not delete outdated documents — archive them with a clear notice at the top: "This document was superseded by [link] on [date]." Audit trails require the history.

---

## 8. Common Documentation Anti-Patterns

The following patterns are the most common failures on SAP projects. The automated QA agent checks for several of these. Human reviewers must check for all of them.

### 1. "See ABAP Code"

A transformation description that says "see routine ZXXX_Y for logic" tells the reader nothing about what the system does or why. ABAP code is an implementation detail — the documentation must describe the business logic in plain language. The code reference may appear as a supplementary pointer after the plain-language description.

### 2. Copy-Paste of SAP Auto-Generated Descriptions

SAP generates short descriptions for InfoObjects, DSOs, and transformations. These are identifiers, not documentation. A field description that reads "Amount in Local Currency" when the field actually stores the group-currency-converted amount after allocation is worse than no description — it is actively misleading.

### 3. Missing Upstream or Downstream References

Object documentation that lists the object's content but does not say what feeds it or what consumes it is useful to no one during an incident. "Where does this data come from?" is the first question asked when a number looks wrong. The documentation must answer it.

### 4. No Business Context — Pure Technical Listing

A document that lists fields, types, and lengths without explaining what the data represents or why the object exists is a schema dump, not documentation. The test: can someone who has never seen SAP understand what business problem this object solves by reading the first two paragraphs?

### 5. Orphan Documents

A document that no other document links to will not be found by the people who need it. Every document must be reachable from at least one other document in the set. The Architecture Overview is the entry point — every major data domain should be reachable from it within two clicks.

### 6. Status Never Updated Beyond "Draft"

A document that was written during design and never promoted to "Active" either means it was never reviewed (problem) or it was reviewed and promoted and the status was never updated (also a problem). Status must reflect actual state.

### 7. Change History Left Empty

"Initial version" is acceptable for the first entry. Every subsequent version must describe what changed. A blank change history on a version 1.4 document means the document cannot be trusted — there is no way to know what version 1.3 said.

### 8. Acceptance Criteria Without Numbers

"The data must be correct" is not an acceptance criterion. An acceptance criterion states a measurable threshold: "Total revenue in BW must be within 0.1% of the S/4HANA financial report for the same period." If the business is not willing to define a tolerance, document that decision explicitly — do not leave the field vague.

---

## 9. Tools and Formats

### Documentation Platform

The primary documentation platform for Horvath customer deliverables is the platform agreed with the customer at project start. Approved platforms: BookStack, Confluence, SAP Enable Now (for process documentation), Microsoft SharePoint with OneNote (where mandated by customer IT policy).

The documentation set for a single project must live in one platform. Split documentation across two wikis creates orphan documents and broken links.

On BookStack and Confluence, use the following structure:

```
[Project Name]
  Architecture
    Architecture Overview
  Development
    Development Guidelines
    Object Documentation (one page per significant object)
  Business Requirements
    [Use Case 1] BRS
    [Use Case 2] BRS
  Data Flows
    [Flow 1]
    [Flow 2]
  Master Data
    [Domain 1]
    [Domain 2]
  Operations
    Operational Runbook — [Process Area]
```

### Diagram Tools

Approved tools: draw.io (diagrams.net), Lucidchart, Mermaid (for code-adjacent documentation). Microsoft Visio is acceptable if the customer team uses it, but export diagrams to PNG/SVG for embedding — do not rely on Visio files remaining accessible.

For Mermaid, use `flowchart LR` for data flow diagrams. Include diagrams in the document source so they render on the platform and are version-controlled with the text.

Do not use PowerPoint or Excel diagrams embedded in wiki pages. They are not searchable, not version-controlled, and render poorly on mobile clients.

### Screenshots

Include screenshots when:
- Documenting a BW or DSP configuration that is not represented in text (e.g., transformation mapping UI, DTP settings)
- Showing what a correctly loaded result looks like for verification
- Illustrating a hierarchy structure that is difficult to represent as a table

Annotate screenshots: add callout boxes or arrows pointing to the relevant configuration element. An unannotated screenshot of a DTP configuration page is not documentation — it is a pixel dump.

Do not use screenshots as a substitute for written description. The screenshot documents state at one point in time; the written description documents intent that survives upgrades.

Resize screenshots to a maximum width of 900px before embedding. Unresized screenshots exported from 4K monitors are unreadable at normal zoom levels.

### File Naming for Attachments

When attaching diagram source files (draw.io XML, Lucidchart export):

```
[DocumentType]_[Domain]_[Subject]_[YYYY-MM-DD].[ext]
```

Example: `FLOW_FI_GL_DeltaLoad_2024-03-15.drawio`

Store attachments in the same wiki page as the document that references them. Do not link to files in shared drives or personal OneDrive folders.

---

*This guideline is maintained by the Horvath Center of Excellence — Data and Analytics. Questions and proposed amendments should be directed to the CoE lead responsible for the engagement.*
