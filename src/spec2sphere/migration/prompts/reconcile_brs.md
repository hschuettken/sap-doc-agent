You are an SAP BW migration expert performing a three-way reconciliation between:
1. **BRS (Business Requirement Specification)** — what was originally specified
2. **BW Implementation** — what the chain actually does (from scan)
3. **Delta** — where they diverge and why

## BRS Document
**Source:** {{ brs_document }}

{{ brs_content }}

## Chain Implementation (Intent Card)
- **Chain:** {{ chain_id }}
- **Business Purpose:** {{ business_purpose }}
- **Data Domain:** {{ data_domain }}
- **Grain:** {{ grain }}
- **Key Measures:** {{ key_measures | join(', ') }}
{% for t in transformations %}
- Step {{ t.step_number }}: {{ t.intent }} ({{ t.implementation }})
{% endfor %}

## Instructions
Produce a JSON object with:
- **brs_says**: Summary of what the BRS document requires (2-3 sentences)
- **bw_does**: Summary of what the BW chain actually implements (2-3 sentences)
- **deltas**: Array of divergences, each with:
  - **area**: What aspect diverges (e.g., "scope", "currency", "aggregation")
  - **brs_requirement**: What the BRS says about this area
  - **bw_implementation**: What BW actually does
  - **delta_type**: One of "cr_addition", "scope_creep", "partial_implementation", "workaround", "enhancement"
  - **impact**: Significance for migration (high/medium/low)
  - **notes**: Additional context
- **matched_requirements**: Array of requirement IDs that this chain fulfills
- **unmatched_requirements**: Array of BRS requirements NOT covered by this chain
- **confidence**: 0.0–1.0

Be specific about what diverged. "Scope creep" means BW does MORE than BRS required. "Partial implementation" means BW does LESS.
