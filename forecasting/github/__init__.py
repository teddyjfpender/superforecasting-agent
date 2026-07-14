"""GitHub App control-plane integration."""

from forecasting.github.auth import GitHubOAuthService
from forecasting.github.app import GitHubAppClient
from forecasting.github.capabilities import (
    CapabilityGitHubClient,
    GitHubCapabilityBroker,
    GitHubPermissionError,
)
from forecasting.github.checks import PromotionCheckPublisher
from forecasting.github.discussion import AgentDiscussionCoordinator, DiscussionLimits
from forecasting.github.events import GitHubWebhookProcessor, record_github_origin
from forecasting.github.installations import GitHubInstallationRegistry, installation_url
from forecasting.github.publisher import GitHubPublisher
from forecasting.github.reconcile import MergeApplyReconciler
from forecasting.github.slack_sync import GitHubSlackMirror
from forecasting.github.webhooks import ingest_github_webhook, mark_delivery_processed

__all__ = [
    "GitHubCapabilityBroker",
    "GitHubAppClient",
    "CapabilityGitHubClient",
    "GitHubOAuthService",
    "GitHubInstallationRegistry",
    "GitHubPermissionError",
    "AgentDiscussionCoordinator",
    "DiscussionLimits",
    "GitHubPublisher",
    "GitHubWebhookProcessor",
    "MergeApplyReconciler",
    "GitHubSlackMirror",
    "PromotionCheckPublisher",
    "record_github_origin",
    "ingest_github_webhook",
    "installation_url",
    "mark_delivery_processed",
]
