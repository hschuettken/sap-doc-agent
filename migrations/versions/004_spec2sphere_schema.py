"""Spec2Sphere multi-tenant schema.

Revision ID: 004
Revises: 003
Create Date: 2026-04-15
"""

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- Tenancy ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS tenants (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS customers (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID REFERENCES tenants(id),
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        branding JSONB DEFAULT '{}',
        policy_overrides JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS projects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        name TEXT NOT NULL,
        slug TEXT NOT NULL,
        environment TEXT DEFAULT 'sandbox',
        status TEXT DEFAULT 'active',
        config JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Users & RBAC ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        role TEXT DEFAULT 'consultant',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS user_customer_access (
        user_id UUID REFERENCES users(id),
        customer_id UUID REFERENCES customers(id),
        role_override TEXT,
        PRIMARY KEY (user_id, customer_id)
    )
    """)

    # ---- Knowledge & Standards ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS knowledge_items (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tenant_id UUID REFERENCES tenants(id),
        customer_id UUID REFERENCES customers(id),
        project_id UUID REFERENCES projects(id),
        category TEXT NOT NULL,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        embedding vector(1536),
        source TEXT,
        confidence FLOAT DEFAULT 1.0,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Landscape Inventory ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS landscape_objects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        project_id UUID REFERENCES projects(id),
        platform TEXT NOT NULL,
        object_type TEXT NOT NULL,
        object_name TEXT NOT NULL,
        technical_name TEXT,
        layer TEXT,
        metadata JSONB DEFAULT '{}',
        documentation TEXT,
        dependencies JSONB DEFAULT '[]',
        last_scanned TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Pipeline: Requirements ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS requirements (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        title TEXT NOT NULL,
        business_domain TEXT,
        description TEXT,
        source_documents JSONB DEFAULT '[]',
        parsed_entities JSONB DEFAULT '{}',
        parsed_kpis JSONB DEFAULT '[]',
        parsed_grain JSONB DEFAULT '{}',
        confidence JSONB DEFAULT '{}',
        open_questions JSONB DEFAULT '[]',
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Pipeline: Architecture Decisions ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS architecture_decisions (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        requirement_id UUID REFERENCES requirements(id),
        topic TEXT NOT NULL,
        choice TEXT NOT NULL,
        alternatives JSONB DEFAULT '[]',
        rationale TEXT,
        platform_placement TEXT,
        status TEXT DEFAULT 'draft',
        approved_by UUID REFERENCES users(id),
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Pipeline: HLA ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS hla_documents (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        requirement_id UUID REFERENCES requirements(id),
        version INT DEFAULT 1,
        content JSONB NOT NULL,
        narrative TEXT,
        status TEXT DEFAULT 'draft',
        approved_by UUID REFERENCES users(id),
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Pipeline: Technical Specifications ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS tech_specs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        hla_id UUID REFERENCES hla_documents(id),
        version INT DEFAULT 1,
        objects JSONB NOT NULL,
        dependency_graph JSONB,
        deployment_order JSONB,
        status TEXT DEFAULT 'draft',
        approved_by UUID REFERENCES users(id),
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Pipeline: Technical Objects ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS technical_objects (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        tech_spec_id UUID REFERENCES tech_specs(id),
        project_id UUID REFERENCES projects(id),
        name TEXT NOT NULL,
        object_type TEXT NOT NULL,
        platform TEXT NOT NULL,
        layer TEXT,
        definition JSONB NOT NULL,
        generated_artifact TEXT,
        implementation_route TEXT,
        route_confidence FLOAT,
        status TEXT DEFAULT 'planned',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Pipeline: SAC Blueprints ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS sac_blueprints (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        tech_spec_id UUID REFERENCES tech_specs(id),
        title TEXT NOT NULL,
        audience TEXT,
        archetype TEXT,
        style_profile JSONB DEFAULT '[]',
        pages JSONB NOT NULL,
        interactions JSONB DEFAULT '{}',
        performance_class TEXT DEFAULT 'standard',
        status TEXT DEFAULT 'draft',
        approved_by UUID REFERENCES users(id),
        approved_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Testing & Reconciliation ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS test_specs (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        tech_spec_id UUID REFERENCES tech_specs(id),
        version INT DEFAULT 1,
        test_mode TEXT DEFAULT 'preservation',
        test_cases JSONB NOT NULL,
        tolerance_rules JSONB DEFAULT '{}',
        expected_deltas JSONB DEFAULT '[]',
        status TEXT DEFAULT 'draft',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS reconciliation_results (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        test_spec_id UUID REFERENCES test_specs(id),
        project_id UUID REFERENCES projects(id),
        test_case_key TEXT NOT NULL,
        baseline_value JSONB,
        candidate_value JSONB,
        delta JSONB,
        delta_status TEXT,
        explanation TEXT,
        approved_by UUID REFERENCES users(id),
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Visual QA ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS visual_qa_results (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        blueprint_id UUID REFERENCES sac_blueprints(id),
        page_id TEXT NOT NULL,
        screenshot_path TEXT,
        expected_layout TEXT,
        result TEXT,
        differences JSONB DEFAULT '[]',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Artifact Lab ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS lab_experiments (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        platform TEXT NOT NULL,
        object_type TEXT NOT NULL,
        experiment_type TEXT NOT NULL,
        input_definition JSONB,
        output_definition JSONB,
        diff JSONB,
        route_used TEXT,
        success BOOLEAN,
        notes TEXT,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS learned_templates (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        platform TEXT NOT NULL,
        object_type TEXT NOT NULL,
        template_definition JSONB NOT NULL,
        mutation_rules JSONB DEFAULT '{}',
        deployment_hints JSONB DEFAULT '{}',
        confidence FLOAT DEFAULT 0.5,
        approved BOOLEAN DEFAULT false,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Route Fitness Tracking ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS route_fitness (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        platform TEXT NOT NULL,
        object_type TEXT NOT NULL,
        action TEXT NOT NULL,
        route TEXT NOT NULL,
        attempts INT DEFAULT 0,
        successes INT DEFAULT 0,
        avg_duration_seconds FLOAT,
        last_failure_reason TEXT,
        fitness_score FLOAT DEFAULT 0.5,
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Approvals ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS approvals (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        project_id UUID REFERENCES projects(id),
        artifact_type TEXT NOT NULL,
        artifact_id UUID NOT NULL,
        status TEXT DEFAULT 'pending',
        reviewer_id UUID REFERENCES users(id),
        comments TEXT,
        checklist JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now(),
        resolved_at TIMESTAMPTZ
    )
    """)

    # ---- Audit Log ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id BIGSERIAL PRIMARY KEY,
        tenant_id UUID,
        customer_id UUID,
        project_id UUID,
        user_id UUID,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        policy_stack_version TEXT,
        retrieval_sources JSONB,
        tool_calls JSONB,
        details JSONB DEFAULT '{}',
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Design System ----
    op.execute("""
    CREATE TABLE IF NOT EXISTS design_tokens (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        token_type TEXT NOT NULL,
        token_name TEXT NOT NULL,
        token_value JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now(),
        UNIQUE(customer_id, token_type, token_name)
    )
    """)

    op.execute("""
    CREATE TABLE IF NOT EXISTS layout_archetypes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        customer_id UUID REFERENCES customers(id),
        name TEXT NOT NULL,
        description TEXT,
        archetype_type TEXT,
        definition JSONB NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """)

    # ---- Indexes ----
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_tenant ON knowledge_items(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_customer ON knowledge_items(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_project ON knowledge_items(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_created ON knowledge_items(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_landscape_customer ON landscape_objects(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_landscape_project ON landscape_objects(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_requirements_project ON requirements(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_requirements_created ON requirements(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_arch_decisions_project ON architecture_decisions(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_hla_project ON hla_documents(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tech_specs_project ON tech_specs(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tech_objects_project ON technical_objects(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tech_objects_spec ON technical_objects(tech_spec_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sac_blueprints_project ON sac_blueprints(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_test_specs_project ON test_specs(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_recon_project ON reconciliation_results(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_customer ON audit_log(customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_project ON audit_log(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log(created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_customers_tenant ON customers(tenant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_projects_customer ON projects(customer_id)")


def downgrade():
    tables = [
        "audit_log",
        "approvals",
        "route_fitness",
        "learned_templates",
        "lab_experiments",
        "visual_qa_results",
        "reconciliation_results",
        "test_specs",
        "sac_blueprints",
        "technical_objects",
        "tech_specs",
        "hla_documents",
        "architecture_decisions",
        "requirements",
        "landscape_objects",
        "knowledge_items",
        "user_customer_access",
        "users",
        "projects",
        "customers",
        "tenants",
        "design_tokens",
        "layout_archetypes",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
