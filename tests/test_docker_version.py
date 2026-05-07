import json
import os
import subprocess
from unittest.mock import patch

import pytest
from cicd.docker_version import (
    compute_docker_tag,
    get_branch,
    get_short_hash,
    get_version,
)


class TestGetVersion:
    def test_reads_version_from_pyproject(
        self, tmp_path, monkeypatch
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "test"\nversion = "1.2.3"\n'
        )
        monkeypatch.chdir(tmp_path)
        assert get_version() == "1.2.3"

    def test_raises_on_missing_version(
        self, tmp_path, monkeypatch
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "test"\n')
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="Version not found"):
            get_version()


class TestGetShortHash:
    def test_uses_git_commit_env(self, monkeypatch) -> None:
        monkeypatch.setenv("GIT_COMMIT", "abc1234def567890")
        assert get_short_hash() == "abc1234"

    def test_falls_back_to_git_rev_parse(
        self, monkeypatch
    ) -> None:
        monkeypatch.delenv("GIT_COMMIT", raising=False)
        with patch(
            "cicd.docker_version.subprocess.check_output",
            return_value=b"abc1234\n",
        ):
            result = get_short_hash()
        assert result == "abc1234"


class TestGetBranch:
    def test_uses_branch_name_env(self, monkeypatch) -> None:
        monkeypatch.setenv("BRANCH_NAME", "feature/test")
        assert get_branch() == "feature/test"

    def test_falls_back_to_git(self, monkeypatch) -> None:
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        with patch(
            "cicd.docker_version.subprocess.check_output",
            return_value=b"feature/my-branch\n",
        ):
            result = get_branch()
        assert result == "feature/my-branch"


class TestComputeDockerTag:
    def test_tagged_release(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "refs/tags/v0.1.0", "abc1234")
            == "0.1.0"
        )

    def test_develop(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "develop", "abc1234")
            == "0.1.0-dev.abc1234"
        )

    def test_main(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "main", "abc1234")
            == "0.1.0.abc1234"
        )

    def test_master(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "master", "abc1234")
            == "0.1.0.abc1234"
        )

    def test_pr_branch(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "PR-3", "abc1234")
            == "0.1.0-pr3.abc1234"
        )

    def test_feature_branch(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "feature/extract", "abc1234")
            == "0.1.0-feat.abc1234"
        )

    def test_hotfix_branch(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "hotfix/fix-bug", "abc1234")
            == "0.1.0-hotfix.abc1234"
        )

    def test_release_branch(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "release/0.2.0", "abc1234")
            == "0.1.0-rc.abc1234"
        )

    def test_other_branch(self) -> None:
        assert (
            compute_docker_tag("0.1.0", "some-branch", "abc1234")
            == "0.1.0.abc1234"
        )


class TestDockerVersionCLI:
    def test_json_output(self, monkeypatch) -> None:
        project_root = os.path.dirname(os.path.dirname(__file__))
        monkeypatch.chdir(project_root)
        monkeypatch.setenv("BRANCH_NAME", "feature/test")
        monkeypatch.setenv("GIT_COMMIT", "abc1234def567890")
        result = subprocess.check_output(
            ["python", "cicd/docker_version.py", "--json"],
            cwd=project_root,
        ).decode()
        data = json.loads(result)
        assert "version" in data
        assert "docker_tag" in data
        assert "branch" in data
        assert "hash" in data
        assert data["version"] == "0.1.0"
        assert data["docker_tag"] == "0.1.0-feat.abc1234"
