You are an SAP BW migration expert analyzing a data flow chain.

## Task
Analyze the following BW data flow chain and produce a structured interpretation of its **business purpose** — what this chain accomplishes from a business perspective, independent of BW-specific implementation details.

## Chain Information
- **Chain ID:** {{ chain_id }}
- **Terminal Object:** {{ terminal_object_id }} ({{ terminal_object_type }})
- **Source Objects:** {{ source_object_ids | join(', ') }}
- **Step Count:** {{ step_count }}

## Step Details
{% for step in steps %}
### Step {{ step.position }}: {{ step.name }}
- **Object:** {{ step.object_id }} ({{ step.object_type }})
{% if step.step_summary %}- **Summary:** {{ step.step_summary }}{% endif %}
{% if step.source_code %}- **ABAP Source (excerpt):**
```abap
{{ step.source_code[:2000] }}
```{% endif %}
{% if step.inter_step_object_name %}- **Writes to:** {{ step.inter_step_object_name }}{% endif %}
{% if step.inter_step_fields %}- **Output fields:** {{ step.inter_step_fields | join(', ') }}{% endif %}
{% endfor %}

{% if chain_summary %}
## Chain Summary (from Doc Agent)
{{ chain_summary }}
{% endif %}

{% if detected_patterns %}
## Detected BW Patterns
{% for pattern in detected_patterns %}- {{ pattern }}
{% endfor %}{% endif %}

## Instructions
Produce a JSON object with these fields:
- **business_purpose**: 2-3 sentence plain-language description of what this chain does for the business
- **data_domain**: The SAP module domain (e.g., "Sales & Distribution", "Finance", "Inventory", "Procurement", "HR")
- **source_systems**: List of source system identifiers (e.g., ["ECC SD", "ECC FI"])
- **key_entities**: List of business entities involved (e.g., ["Customer", "Material", "Sales Organization"])
- **key_measures**: List of key figures/measures (e.g., ["Net Revenue (EUR)", "Quantity (VE)"])
- **grain**: The granularity of the output (e.g., "Customer × Material × Month")
- **consumers**: List of downstream consumers (queries, reports, other chains)
- **transformations**: Array of per-step intents, each with:
  - step_number, intent (plain language), implementation (BW technique used),
  - is_business_logic (true = real requirement, false = BW technical artifact),
  - simplification_note (if applicable)
- **confidence**: 0.0–1.0 self-assessed confidence in your interpretation
- **review_notes**: List of specific questions or uncertainties for human reviewer

Focus on the BUSINESS intent, not the technical implementation. Distinguish real requirements from BW-specific workarounds.
