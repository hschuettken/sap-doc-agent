-- SAP Analytics Cloud — Analytic Model bindings for dsp-ai briefings.
--
-- Install this SQL inside the client's Datasphere tenant. SAC then consumes
-- ``dsp_ai.latest_briefings`` natively via Live Data Model, so the Morning
-- Brief narrative renders inside every SAC Story with zero widget code.

-- ---------------------------------------------------------------------------
-- Latest briefing per (enhancement, user, context) — handles expires_at.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dsp_ai.latest_briefings AS
SELECT
    b.enhancement_id,
    e.name              AS enhancement_name,
    b.user_id,
    b.context_key,
    b.narrative_text,
    b.key_points,
    b.suggested_actions,
    b.render_hint,
    b.generated_at,
    b.generation_id,
    e.version           AS enhancement_version,
    e.config ->> 'render_hint' AS config_render_hint
FROM dsp_ai.briefings b
JOIN dsp_ai.enhancements e ON e.id = b.enhancement_id
WHERE b.expires_at IS NULL OR b.expires_at > NOW();

COMMENT ON VIEW dsp_ai.latest_briefings IS
    'SAC-facing view of dsp_ai.briefings. Filter by user_id via SAC session '
    'variable ($user), then by enhancement_name or context_key.';


-- ---------------------------------------------------------------------------
-- Ranked items — top-N lists (populated in Session B when ranking
-- enhancements ship; view exists now so SAC bindings can be pre-wired).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW dsp_ai.latest_rankings AS
SELECT
    r.enhancement_id,
    e.name      AS enhancement_name,
    r.user_id,
    r.context_key,
    r.item_id,
    r.rank,
    r.score,
    r.reason,
    r.generated_at,
    r.generation_id
FROM dsp_ai.rankings r
JOIN dsp_ai.enhancements e ON e.id = r.enhancement_id;

COMMENT ON VIEW dsp_ai.latest_rankings IS
    'Ranked output for SAC bindings. Filter by enhancement_name + rank <= N.';


-- ---------------------------------------------------------------------------
-- Read role — grant to the SAC service principal.
-- Replace ``sac_service_user`` with the actual role at install time.
-- ---------------------------------------------------------------------------
-- GRANT USAGE ON SCHEMA dsp_ai TO sac_service_user;
-- GRANT SELECT ON dsp_ai.latest_briefings  TO sac_service_user;
-- GRANT SELECT ON dsp_ai.latest_rankings   TO sac_service_user;
