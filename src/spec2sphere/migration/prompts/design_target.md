You are designing a target SAP Datasphere architecture for a BW migration.

## Chain: {{ chain_id }}
**Business Purpose:** {{ business_purpose }}
**Data Domain:** {{ data_domain }}
**Grain:** {{ grain }}
**Current Classification:** {{ classification }}
**Effort Category:** {{ effort_category }}

## BW Source Steps
{% for step in steps %}
### Step {{ step.step_number }}: {{ step.intent }}
- **Implementation:** {{ step.implementation }}
- **Business Logic:** {{ step.is_business_logic }}
{% if step.simplification_note %}- **Simplification Note:** {{ step.simplification_note }}{% endif %}
{% if step.detected_patterns %}- **Detected Patterns:** {{ step.detected_patterns | join(", ") }}{% endif %}
{% if step.dsp_equivalent %}- **DSP Equivalent:** {{ step.dsp_equivalent }}{% endif %}
{% endfor %}

## Step Classifications
{% for sc in step_classifications %}
- Step {{ sc.step_number }} ({{ sc.object_id }}): **{{ sc.classification }}** — {{ sc.rationale }}{% if sc.dsp_equivalent %} → DSP: {{ sc.dsp_equivalent }}{% endif %}
{% endfor %}

## DSP Architecture Rules (MANDATORY)

### Naming Conventions
{% for key, prefix in naming_prefixes %}
- {{ prefix }} = {{ key[0] }} / {{ key[1] }}
{% endfor %}

### SQL Rules
{% for rule in sql_rules %}
- **{{ rule.rule_id }}** ({{ rule.severity }}): {{ rule.description }}
{% endfor %}

### 4-Layer Architecture
1. **Staging (01_)**: Raw replicated tables — no transforms
2. **Harmonization (02_)**: Integration views — joins, filters, field mapping, type conversion
3. **Mart (03_)**: Semantic/fact views for consumption — aggregation, business KPIs
4. **Consumption**: Analytic Models for SAC — replaces BEx queries

### Persistence Strategy
- Persist views with: CROSS JOIN, >30s preview, 3+ downstream consumers
- Do NOT persist staging/intermediate views (wastes disk)

### Step Collapse Principle
Where BW uses multiple intermediate DSOs for delta handling or partitioning, DSP can often collapse into fewer views. For each view, document which BW steps it replaces and why.

## Your Task

Design the DSP target views for this chain. Return a JSON object with:

```json
{
  "views": [
    {
      "technical_name": "02_RV_...",
      "space": "SAP_ADMIN",
      "layer": "harmonization|mart|staging",
      "semantic_usage": "relational_dataset|fact|dimension|text|hierarchy",
      "description": "What this view does",
      "source_chains": ["{{ chain_id }}"],
      "source_objects": ["upstream_view_or_table"],
      "sql_logic": "SQL sketch showing the logic (not final code)",
      "collapse_rationale": "Why BW steps X-Y are merged into this view",
      "collapsed_bw_steps": ["step_ids_replaced"],
      "persistence": true/false,
      "persistence_rationale": "why persist (only if true)"
    }
  ]
}
```

Focus on:
1. **Collapse** — merge BW steps where possible, document why
2. **Naming** — use correct prefixes per layer/usage
3. **Persistence** — only where needed (CROSS JOIN, slow, many consumers)
4. **Traceability** — every view traces back to BW source steps
