You are an SAP BW migration expert classifying a data flow chain for migration to SAP Datasphere.

## Chain Intent
- **Chain ID:** {{ chain_id }}
- **Business Purpose:** {{ business_purpose }}
- **Data Domain:** {{ data_domain }}
- **Grain:** {{ grain }}

## Transformation Steps
{% for t in transformations %}
### Step {{ t.step_number }}: {{ t.intent }}
- **Implementation:** {{ t.implementation }}
- **Is Business Logic:** {{ t.is_business_logic }}
{% if t.simplification_note %}- **Simplification Note:** {{ t.simplification_note }}{% endif %}
{% if t.detected_patterns %}- **Detected Patterns:** {{ t.detected_patterns | join(', ') }}{% endif %}
{% endfor %}

{% if detected_patterns %}
## Detected BW Patterns (rule-based)
{% for p in detected_patterns %}- **{{ p.name }}** ({{ p.classification }}): {{ p.description }} → DSP: {{ p.dsp_equivalent }}
{% endfor %}{% endif %}

{% if activity_data %}
## Activity Data
- **Last Execution:** {{ activity_data.last_execution or 'Unknown' }}
- **Query Usage Count:** {{ activity_data.query_usage_count if activity_data.query_usage_count is not none else 'Unknown' }}
{% endif %}

## Classification Options
- **MIGRATE**: Real business need, design fresh for DSP
- **SIMPLIFY**: Real need, but BW over-engineered it — simpler DSP equivalent exists
- **REPLACE**: DSP has a native equivalent (replication flows, DACs, etc.)
- **DROP**: Dead code, superseded, or one-off workaround — verify with business owner
- **CLARIFY**: Ambiguous intent, too complex for auto-classification, needs human decision

## Instructions
Produce a JSON object with:
- **classification**: One of "migrate", "simplify", "replace", "drop", "clarify"
- **rationale**: 2-3 sentence explanation of why this classification
- **step_classifications**: Array per step with step_number, classification, rationale, dsp_equivalent
- **dsp_equivalent_pattern**: If SIMPLIFY/REPLACE, describe the DSP-native equivalent
- **effort_category**: "trivial", "moderate", or "complex"
- **effort_rationale**: Why this effort level
- **confidence**: 0.0–1.0
- **needs_human_review**: true if uncertain or DROP candidate

Consider rule-based pattern matches as strong signals. If most steps are SIMPLIFY, the chain is likely SIMPLIFY.
