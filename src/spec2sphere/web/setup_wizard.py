"""First-run setup wizard for Spec2Sphere.

When the setup marker file is absent, all UI requests are redirected to
/ui/setup/welcome.  The wizard walks through 7 steps and writes the marker
on completion.  Once the marker exists the wizard routes return 404 and the
redirect middleware is disabled — existing deployments are completely unaffected.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Marker file location — override with SETUP_MARKER env var.
# ------------------------------------------------------------------
_DEFAULT_MARKER = "/var/spec2sphere/setup.complete"


def _marker_path() -> Path:
    return Path(os.environ.get("SETUP_MARKER", _DEFAULT_MARKER))


def setup_complete() -> bool:
    """Return True if setup is complete.

    Setup is considered complete when EITHER:
    - The setup wizard is not enabled (`SETUP_WIZARD_ENABLED` is unset/falsey) — default.
      This keeps existing deployments and test fixtures unaffected.
    - OR the marker file exists at `SETUP_MARKER` path.
    """
    if os.environ.get("SETUP_WIZARD_ENABLED", "").lower() not in {"1", "true", "yes"}:
        return True
    return _marker_path().exists()


# ------------------------------------------------------------------
# Middleware — redirects to wizard when marker is absent.
# ------------------------------------------------------------------

# Paths that bypass the wizard redirect (prefix-matched).
_BYPASS_PREFIXES = (
    "/ui/setup",
    "/static",
    "/api",
    "/docs",
    "/sitemap",
    "/health",
    "/healthz",
    "/readyz",
    "/metrics",
    "/copilot",
    "/mcp",
    "/reports",
    "/objects",
    "/openapi",
)


class SetupWizardMiddleware(BaseHTTPMiddleware):
    """Redirect all UI traffic to the setup wizard until setup is complete.

    Must be placed BEFORE AuthMiddleware in the middleware stack so that no
    login is required during first-run setup.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        if setup_complete():
            return await call_next(request)

        path = request.url.path

        # Always pass through bypass paths.
        if any(path.startswith(prefix) for prefix in _BYPASS_PREFIXES):
            return await call_next(request)

        # Redirect everything else (e.g. /, /ui/dashboard, …) to welcome.
        return RedirectResponse("/ui/setup/welcome", status_code=302)


# ------------------------------------------------------------------
# Wizard router
# ------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).parent / "templates"
_templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

STEPS = ["welcome", "admin", "db", "llm", "privacy", "sap", "done"]
STEP_LABELS = {
    "welcome": "Welcome",
    "admin": "Admin Credentials",
    "db": "Database",
    "llm": "LLM Routing",
    "privacy": "Privacy",
    "sap": "SAP Source",
    "done": "Finish",
}


def _step_index(step: str) -> int:
    try:
        return STEPS.index(step)
    except ValueError:
        return 0


def _render(request: Request, template: str, ctx: dict) -> HTMLResponse:
    ctx["request"] = request
    return _templates.TemplateResponse(request, template, ctx)


def _wizard_ctx(step: str) -> dict:
    idx = _step_index(step)
    return {
        "step": step,
        "step_index": idx,
        "step_number": idx + 1,
        "total_steps": len(STEPS),
        "steps": STEPS,
        "step_labels": STEP_LABELS,
        "prev_step": STEPS[idx - 1] if idx > 0 else None,
        "next_step": STEPS[idx + 1] if idx < len(STEPS) - 1 else None,
    }


def create_setup_wizard_router() -> APIRouter:
    """Return the wizard APIRouter.  All routes return 404 once setup is complete."""
    router = APIRouter(prefix="/ui/setup")

    def _check_disabled():
        """Raise 404 if wizard is already done."""
        from fastapi import HTTPException

        if setup_complete():
            raise HTTPException(status_code=404, detail="Setup already completed")

    # ---- Welcome ----

    @router.get("/welcome", response_class=HTMLResponse)
    async def wizard_welcome(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("welcome")
        return _render(request, "setup/welcome.html", ctx)

    # ---- Admin credentials ----

    @router.get("/admin", response_class=HTMLResponse)
    async def wizard_admin(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("admin")
        ctx["error"] = request.query_params.get("error", "")
        return _render(request, "setup/admin.html", ctx)

    @router.post("/admin", response_class=HTMLResponse)
    async def wizard_admin_post(request: Request):
        _check_disabled()
        form = await request.form()
        password = str(form.get("password", "")).strip()
        confirm = str(form.get("confirm", "")).strip()

        if not password or len(password) < 6:
            return RedirectResponse("/ui/setup/admin?error=Password+must+be+at+least+6+characters", status_code=303)
        if password != confirm:
            return RedirectResponse("/ui/setup/admin?error=Passwords+do+not+match", status_code=303)

        # Hash and persist to env file.
        from spec2sphere.web.auth import hash_password

        pw_hash = hash_password(password)
        os.environ["SAP_DOC_AGENT_UI_PASSWORD_HASH"] = pw_hash
        _write_env_key("SAP_DOC_AGENT_UI_PASSWORD_HASH", pw_hash)

        return RedirectResponse("/ui/setup/db", status_code=303)

    # ---- Database ----

    @router.get("/db", response_class=HTMLResponse)
    async def wizard_db(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("db")
        ctx["db_url"] = os.environ.get("DATABASE_URL", "")
        ctx["error"] = request.query_params.get("error", "")
        ctx["ok"] = request.query_params.get("ok", "")
        return _render(request, "setup/db.html", ctx)

    @router.post("/db", response_class=HTMLResponse)
    async def wizard_db_post(request: Request):
        _check_disabled()
        form = await request.form()
        db_url = str(form.get("db_url", "")).strip()
        action = str(form.get("action", "next"))

        if db_url:
            os.environ["DATABASE_URL"] = db_url
            _write_env_key("DATABASE_URL", db_url)

        if action == "test":
            ok, msg = await _test_db(os.environ.get("DATABASE_URL", ""))
            if ok:
                return RedirectResponse(f"/ui/setup/db?ok={msg}", status_code=303)
            return RedirectResponse(f"/ui/setup/db?error={msg}", status_code=303)

        return RedirectResponse("/ui/setup/llm", status_code=303)

    # ---- LLM routing ----

    @router.get("/llm", response_class=HTMLResponse)
    async def wizard_llm(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("llm")
        ctx["current_profile"] = os.environ.get("LLM_PROFILE", "default")
        ctx["error"] = request.query_params.get("error", "")
        return _render(request, "setup/llm.html", ctx)

    @router.post("/llm", response_class=HTMLResponse)
    async def wizard_llm_post(request: Request):
        _check_disabled()
        form = await request.form()
        profile = str(form.get("profile", "default"))
        api_key = str(form.get("anthropic_api_key", "")).strip()

        valid_profiles = ("default", "all-local", "all-claude")
        if profile not in valid_profiles:
            profile = "default"

        os.environ["LLM_PROFILE"] = profile
        _write_env_key("LLM_PROFILE", profile)

        if api_key and profile == "all-claude":
            os.environ["ANTHROPIC_API_KEY"] = api_key
            _write_env_key("ANTHROPIC_API_KEY", api_key)

        return RedirectResponse("/ui/setup/privacy", status_code=303)

    # ---- Privacy ----

    @router.get("/privacy", response_class=HTMLResponse)
    async def wizard_privacy(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("privacy")
        ctx["local_only"] = os.environ.get("LOCAL_ONLY_WITH_DATA", "false").lower() == "true"
        return _render(request, "setup/privacy.html", ctx)

    @router.post("/privacy", response_class=HTMLResponse)
    async def wizard_privacy_post(request: Request):
        _check_disabled()
        form = await request.form()
        local_only = "local_only" in form

        val = "true" if local_only else "false"
        os.environ["LOCAL_ONLY_WITH_DATA"] = val
        _write_env_key("LOCAL_ONLY_WITH_DATA", val)

        return RedirectResponse("/ui/setup/sap", status_code=303)

    # ---- SAP Source (optional) ----

    @router.get("/sap", response_class=HTMLResponse)
    async def wizard_sap(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("sap")
        ctx["error"] = request.query_params.get("error", "")
        return _render(request, "setup/sap.html", ctx)

    @router.post("/sap", response_class=HTMLResponse)
    async def wizard_sap_post(request: Request):
        _check_disabled()
        form = await request.form()
        skip = "skip" in form

        if not skip:
            dsp_url = str(form.get("dsp_url", "")).strip()
            dsp_user = str(form.get("dsp_user", "")).strip()
            dsp_pass = str(form.get("dsp_pass", "")).strip()

            if dsp_url:
                os.environ["DSP_BASE_URL"] = dsp_url
                _write_env_key("DSP_BASE_URL", dsp_url)
            if dsp_user:
                os.environ["DSP_USERNAME"] = dsp_user
                _write_env_key("DSP_USERNAME", dsp_user)
            if dsp_pass:
                os.environ["DSP_PASSWORD"] = dsp_pass
                _write_env_key("DSP_PASSWORD", dsp_pass)

        return RedirectResponse("/ui/setup/done", status_code=303)

    # ---- Done / finish ----

    @router.get("/done", response_class=HTMLResponse)
    async def wizard_done(request: Request):
        _check_disabled()
        ctx = _wizard_ctx("done")
        return _render(request, "setup/done.html", ctx)

    @router.post("/done", response_class=HTMLResponse)
    async def wizard_done_post(request: Request):
        _check_disabled()
        _write_marker()
        return RedirectResponse("/ui/dashboard", status_code=303)

    return router


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _write_marker() -> None:
    """Create the setup.complete marker file."""
    marker = _marker_path()
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
        logger.info("Setup wizard complete — marker written to %s", marker)
    except OSError as exc:
        logger.warning("Could not write setup marker to %s: %s — trying fallback", marker, exc)
        # Fallback: write next to config.yaml in cwd
        fallback = Path("setup.complete")
        fallback.touch(exist_ok=True)
        os.environ["SETUP_MARKER"] = str(fallback.resolve())
        logger.info("Marker written to fallback path %s", fallback.resolve())


def _write_env_key(key: str, value: str) -> None:
    """Best-effort: persist a key=value into .env in the project root."""
    try:
        env_file = Path(".env")
        if env_file.exists():
            content = env_file.read_text()
        else:
            content = ""
        lines = content.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                found = True
                break
        if not found:
            lines.append(f"{key}={value}")
        env_file.write_text("\n".join(lines) + "\n")
    except OSError:
        pass  # Non-fatal — env vars are already set in-process


async def _test_db(db_url: str) -> tuple[bool, str]:
    """Attempt a simple SELECT 1 against the given Postgres URL."""
    if not db_url:
        return False, "No+database+URL+provided"
    try:
        import asyncpg

        conn_url = db_url.replace("postgresql+psycopg://", "postgresql://").replace(
            "postgresql+asyncpg://", "postgresql://"
        )
        conn = await asyncpg.connect(conn_url, timeout=5)
        await conn.fetchval("SELECT 1")
        await conn.close()
        return True, "Connected+successfully"
    except Exception as exc:
        safe = str(exc).replace(" ", "+").replace("&", "and")[:100]
        return False, safe
