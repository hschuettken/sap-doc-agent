import pytest
from unittest.mock import MagicMock, patch
from spec2sphere.config import GitConfig
from spec2sphere.git_backend import create_git_backend
from spec2sphere.git_backend.base import GitBackend
from spec2sphere.git_backend.github_backend import GitHubBackend


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    content = MagicMock()
    content.sha = "abc123"
    content.decoded_content = b"# Old content"
    repo.get_contents.return_value = content
    repo.create_file.return_value = {"commit": MagicMock(sha="new123")}
    repo.update_file.return_value = {"commit": MagicMock(sha="upd123")}
    return repo


@pytest.fixture
def backend(mock_repo):
    with patch("spec2sphere.git_backend.github_backend.Github") as mock_gh:
        mock_gh.return_value.get_repo.return_value = mock_repo
        return GitHubBackend(token="test-token", repo_name="user/sap-docs")


def test_github_is_backend(backend):
    assert isinstance(backend, GitBackend)


def test_write_creates_new(backend, mock_repo):
    from github import GithubException

    mock_repo.get_contents.side_effect = GithubException(404, {}, {})
    backend.write_file("objects/ADSO.md", "# ADSO", "Add ADSO")
    mock_repo.create_file.assert_called_once()


def test_write_updates_existing(backend, mock_repo):
    backend.write_file("objects/ADSO.md", "# Updated", "Update ADSO")
    mock_repo.update_file.assert_called_once()


def test_read_file(backend):
    assert backend.read_file("objects/ADSO.md") == "# Old content"


def test_read_not_found(backend, mock_repo):
    from github import GithubException

    mock_repo.get_contents.side_effect = GithubException(404, {}, {})
    assert backend.read_file("nonexistent.md") is None


def test_list_files(backend, mock_repo):
    f1, f2 = MagicMock(), MagicMock()
    f1.path, f1.type = "a.md", "file"
    f2.path, f2.type = "b.md", "file"
    mock_repo.get_contents.return_value = [f1, f2]
    assert len(backend.list_files("objects")) == 2


# Factory tests
def test_factory_github(monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "user/repo")
    monkeypatch.setenv("GIT_TOKEN", "ghp_test")
    with patch("spec2sphere.git_backend.github_backend.Github"):
        assert isinstance(
            create_git_backend(GitConfig(type="github", url_env="GIT_REPO_URL", token_env="GIT_TOKEN")), GitHubBackend
        )


def test_factory_missing_env(monkeypatch):
    monkeypatch.delenv("GIT_TOKEN", raising=False)
    with pytest.raises(ValueError, match="environment variable"):
        create_git_backend(GitConfig(type="github", url_env="GIT_REPO_URL", token_env="GIT_TOKEN"))


def test_factory_unsupported(monkeypatch):
    # GitConfig.type is a Pydantic Literal — unknown values are rejected at model
    # construction time before create_git_backend is ever called.
    from pydantic import ValidationError

    monkeypatch.setenv("GIT_REPO_URL", "r")
    monkeypatch.setenv("GIT_TOKEN", "t")
    with pytest.raises((ValueError, ValidationError)):
        create_git_backend(GitConfig(type="bitbucket", url_env="GIT_REPO_URL", token_env="GIT_TOKEN"))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# GitLab backend tests
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Minimal httpx.Response stand-in."""

    def __init__(self, status_code: int, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body

    @property
    def text(self):
        return self._body if isinstance(self._body, str) else ""

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=MagicMock(),
                response=MagicMock(status_code=self.status_code),
            )


@pytest.fixture
def gitlab_backend():
    from spec2sphere.git_backend.gitlab_backend import GitLabBackend

    return GitLabBackend(token="gl-token", repo_name="mygroup/myrepo", branch="main")


def test_gitlab_is_backend(gitlab_backend):
    assert isinstance(gitlab_backend, GitBackend)


def test_gitlab_read_file(gitlab_backend):
    import base64

    encoded = base64.b64encode(b"# Hello").decode()
    with patch("httpx.get", return_value=_FakeResponse(200, {"content": encoded})):
        result = gitlab_backend.read_file("docs/page.md")
    assert result == "# Hello"


def test_gitlab_read_file_not_found(gitlab_backend):
    with patch("httpx.get", return_value=_FakeResponse(404)):
        result = gitlab_backend.read_file("missing.md")
    assert result is None


def test_gitlab_write_file_creates(gitlab_backend):
    """When GET returns 404 a POST (create) is made."""
    with (
        patch("httpx.get", return_value=_FakeResponse(404)),
        patch("httpx.post", return_value=_FakeResponse(201, {})) as mock_post,
    ):
        gitlab_backend.write_file("docs/new.md", "# New", "Add new")
    mock_post.assert_called_once()


def test_gitlab_write_file_updates(gitlab_backend):
    """When GET returns 200 a PUT (update) is made."""
    import base64

    encoded = base64.b64encode(b"old").decode()
    with (
        patch("httpx.get", return_value=_FakeResponse(200, {"content": encoded})),
        patch("httpx.put", return_value=_FakeResponse(200, {})) as mock_put,
    ):
        gitlab_backend.write_file("docs/existing.md", "# Updated", "Update")
    mock_put.assert_called_once()


def test_gitlab_list_files(gitlab_backend):
    tree = [
        {"path": "docs/a.md", "type": "blob"},
        {"path": "docs/b.md", "type": "blob"},
        {"path": "docs/sub", "type": "tree"},
    ]
    with patch("httpx.get", return_value=_FakeResponse(200, tree)):
        files = gitlab_backend.list_files("docs")
    assert files == ["docs/a.md", "docs/b.md"]


def test_gitlab_list_files_not_found(gitlab_backend):
    with patch("httpx.get", return_value=_FakeResponse(404)):
        assert gitlab_backend.list_files("nonexistent") == []


def test_gitlab_delete_file(gitlab_backend):
    with patch("httpx.delete", return_value=_FakeResponse(204, {})) as mock_del:
        gitlab_backend.delete_file("docs/old.md", "Remove old")
    mock_del.assert_called_once()


def test_gitlab_delete_file_not_found(gitlab_backend):
    """404 on delete is a no-op."""
    with patch("httpx.delete", return_value=_FakeResponse(404)):
        gitlab_backend.delete_file("nonexistent.md", "Remove")  # should not raise


def test_factory_gitlab(monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "mygroup/myrepo")
    monkeypatch.setenv("GIT_TOKEN", "gl-token")
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.com")
    from spec2sphere.git_backend.gitlab_backend import GitLabBackend

    result = create_git_backend(GitConfig(type="gitlab", url_env="GIT_REPO_URL", token_env="GIT_TOKEN"))
    assert isinstance(result, GitLabBackend)


# ---------------------------------------------------------------------------
# Azure DevOps backend tests
# ---------------------------------------------------------------------------


@pytest.fixture
def ado_backend():
    from spec2sphere.git_backend.azure_devops_backend import AzureDevOpsBackend

    return AzureDevOpsBackend(token="ado-pat", repo_url="myorg/myproject/myrepo", branch="main")


def test_ado_is_backend(ado_backend):
    assert isinstance(ado_backend, GitBackend)


def test_ado_invalid_repo_url():
    from spec2sphere.git_backend.azure_devops_backend import AzureDevOpsBackend

    with pytest.raises(ValueError, match="org/project/repo"):
        AzureDevOpsBackend(token="t", repo_url="bad-format")


def test_ado_read_file(ado_backend):
    with patch("httpx.get", return_value=_FakeResponse(200, "# Content")) as mock_get:
        # Override text property behaviour: _FakeResponse.text returns the body when str
        result = ado_backend.read_file("docs/page.md")
    assert result == "# Content"


def test_ado_read_file_not_found(ado_backend):
    with patch("httpx.get", return_value=_FakeResponse(404)):
        assert ado_backend.read_file("missing.md") is None


def test_ado_list_files(ado_backend):
    items = [
        {"path": "/docs/a.md", "gitObjectType": "blob"},
        {"path": "/docs/b.md", "gitObjectType": "blob"},
        {"path": "/docs", "gitObjectType": "tree"},
    ]
    with patch("httpx.get", return_value=_FakeResponse(200, {"value": items})):
        files = ado_backend.list_files("docs")
    assert "docs/a.md" in files
    assert "docs/b.md" in files
    assert len(files) == 2


def test_ado_list_files_not_found(ado_backend):
    with patch("httpx.get", return_value=_FakeResponse(404)):
        assert ado_backend.list_files("nonexistent") == []


def test_ado_write_file_creates(ado_backend):
    """File doesn't exist → changeType 'add'."""
    refs_resp = _FakeResponse(200, {"value": [{"objectId": "deadbeef" * 5}]})
    push_resp = _FakeResponse(201, {})

    def fake_get(url, **kwargs):
        if "/refs" in url:
            return refs_resp
        return _FakeResponse(404)  # read_file check

    with patch("httpx.get", side_effect=fake_get), patch("httpx.post", return_value=push_resp) as mock_post:
        ado_backend.write_file("docs/new.md", "# New", "Add new")

    mock_post.assert_called_once()
    payload = mock_post.call_args.kwargs["json"]
    assert payload["commits"][0]["changes"][0]["changeType"] == "add"


def test_ado_write_file_updates(ado_backend):
    """File exists → changeType 'edit'."""
    refs_resp = _FakeResponse(200, {"value": [{"objectId": "deadbeef" * 5}]})
    push_resp = _FakeResponse(201, {})

    def fake_get(url, **kwargs):
        if "/refs" in url:
            return refs_resp
        return _FakeResponse(200, "# Existing")  # read_file returns content

    with patch("httpx.get", side_effect=fake_get), patch("httpx.post", return_value=push_resp) as mock_post:
        ado_backend.write_file("docs/existing.md", "# Updated", "Edit")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["commits"][0]["changes"][0]["changeType"] == "edit"


def test_ado_delete_file(ado_backend):
    refs_resp = _FakeResponse(200, {"value": [{"objectId": "deadbeef" * 5}]})
    push_resp = _FakeResponse(201, {})

    def fake_get(url, **kwargs):
        if "/refs" in url:
            return refs_resp
        return _FakeResponse(200, "# Content")  # file exists

    with patch("httpx.get", side_effect=fake_get), patch("httpx.post", return_value=push_resp) as mock_post:
        ado_backend.delete_file("docs/old.md", "Remove old")

    payload = mock_post.call_args.kwargs["json"]
    assert payload["commits"][0]["changes"][0]["changeType"] == "delete"


def test_ado_delete_file_not_found(ado_backend):
    """If file doesn't exist, delete is a no-op."""
    with patch("httpx.get", return_value=_FakeResponse(404)), patch("httpx.post") as mock_post:
        ado_backend.delete_file("missing.md", "Remove")
    mock_post.assert_not_called()


def test_factory_azure_devops(monkeypatch):
    monkeypatch.setenv("GIT_REPO_URL", "myorg/myproject/myrepo")
    monkeypatch.setenv("GIT_TOKEN", "ado-pat")
    from spec2sphere.git_backend.azure_devops_backend import AzureDevOpsBackend

    result = create_git_backend(GitConfig(type="azure_devops", url_env="GIT_REPO_URL", token_env="GIT_TOKEN"))
    assert isinstance(result, AzureDevOpsBackend)
