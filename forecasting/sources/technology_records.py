"""Technology records for evidence source adapters."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GitHubRelease:
    repo: str
    release_id: str | None
    tag_name: str
    name: str
    body: str
    url: str | None
    html_url: str | None
    created_at: str | None
    published_at: str | None
    draft: bool
    prerelease: bool
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class GitHubRepositorySnapshot:
    repo: str
    repo_id: str | None
    owner_login: str | None
    description: str
    language: str | None
    default_branch: str | None
    visibility: str | None
    license_spdx_id: str | None
    topics: list[str]
    archived: bool
    disabled: bool
    fork: bool
    stargazers_count: int | None
    watchers_count: int | None
    forks_count: int | None
    open_issues_count: int | None
    subscribers_count: int | None
    network_count: int | None
    created_at: str | None
    updated_at: str | None
    pushed_at: str | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class GitHubIssue:
    repo: str
    issue_number: int | None
    title: str
    state: str | None
    is_pull_request: bool
    author: str | None
    labels: list[str]
    created_at: str | None
    updated_at: str | None
    closed_at: str | None
    comments: int | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class GitHubCommit:
    repo: str
    sha: str
    short_sha: str
    message: str
    author_name: str | None
    author_login: str | None
    authored_at: str | None
    committed_at: str | None
    comments: int | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class GitHubWorkflowRun:
    repo: str
    run_id: str
    name: str
    display_title: str
    status: str | None
    conclusion: str | None
    event: str | None
    head_branch: str | None
    head_sha: str | None
    short_sha: str | None
    workflow_id: str | None
    workflow_url: str | None
    actor_login: str | None
    triggering_actor_login: str | None
    run_started_at: str | None
    created_at: str | None
    updated_at: str | None
    url: str | None
    html_url: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class PypiRelease:
    package: str
    version: str
    summary: str
    url: str | None
    project_url: str | None
    uploaded_at: str | None
    latest_upload_at: str | None
    file_count: int
    package_types: list[str]
    python_versions: list[str]
    yanked: bool
    yanked_reason: str | None
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class NpmPackageVersion:
    package: str
    version: str
    description: str
    url: str | None
    tarball_url: str | None
    published_at: str | None
    license: str | None
    maintainers: list[str]
    keywords: list[str]
    deprecated: str | None
    dependency_count: int
    source_name: str
    entry_id: str
    raw: dict


@dataclass(frozen=True)
class NvdCve:
    cve_id: str
    description: str
    url: str | None
    published_at: str | None
    last_modified_at: str | None
    vuln_status: str | None
    severity: str | None
    base_score: float | None
    cvss_version: str | None
    references: list[str]
    source_identifier: str | None
    source_name: str
    entry_id: str | None
    raw: dict


@dataclass(frozen=True)
class CisaKevVulnerability:
    cve_id: str
    vendor_project: str | None
    product: str | None
    vulnerability_name: str
    short_description: str
    date_added: str | None
    due_date: str | None
    required_action: str
    ransomware_use: str | None
    notes: str | None
    cwes: list[str]
    source_url: str | None
    source_name: str
    entry_id: str | None
    raw: dict
