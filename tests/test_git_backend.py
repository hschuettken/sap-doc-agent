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
    monkeypatch.setenv("GIT_REPO_URL", "r")
    monkeypatch.setenv("GIT_TOKEN", "t")
    with pytest.raises(ValueError, match="not yet implemented"):
        create_git_backend(GitConfig(type="gitlab", url_env="GIT_REPO_URL", token_env="GIT_TOKEN"))
