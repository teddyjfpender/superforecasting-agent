"""AWS credential-source and region discovery, independent of client construction.

Importing this module loads no SDK and installs nothing. Explicit discovery may
consult the installed SDK chain, including metadata services. Source presence is
not proof of successful authentication, model access or quota.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# ---------------------------------------------------------------------------
# AWS credential detection
# ---------------------------------------------------------------------------

# Priority order matches OpenClaw's resolveAwsSdkEnvVarName():
#   1. AWS_BEARER_TOKEN_BEDROCK (Bedrock-specific bearer token)
#   2. AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY (explicit IAM credentials)
#   3. AWS_PROFILE (named profile → SSO, assume-role, etc.)
#   4. Implicit: instance role, ECS task role, Lambda execution role
_AWS_CREDENTIAL_ENV_VARS = [
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_ACCESS_KEY_ID",
    "AWS_PROFILE",
    # These are checked by boto3's default chain but we list them for
    # has_aws_credentials() detection:
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_WEB_IDENTITY_TOKEN_FILE",
]


def resolve_aws_auth_env_var(env: Mapping[str, str] | None = None) -> str | None:
    """Return the name of the AWS auth source that is active, or None.

    Checks environment variables first, then falls back to boto3's credential
    chain for implicit sources (EC2 IMDS, ECS task role, etc.).

    Environment matches are configuration hints. The installed SDK chain may
    refresh credentials or query metadata services; this is not a passive read.
    """
    env = env if env is not None else os.environ
    # Bearer token takes highest priority
    if env.get("AWS_BEARER_TOKEN_BEDROCK", "").strip():
        return "AWS_BEARER_TOKEN_BEDROCK"
    # Explicit access key pair
    if (
        env.get("AWS_ACCESS_KEY_ID", "").strip()
        and env.get("AWS_SECRET_ACCESS_KEY", "").strip()
    ):
        return "AWS_ACCESS_KEY_ID"
    # Named profile (SSO, assume-role, etc.)
    if env.get("AWS_PROFILE", "").strip():
        return "AWS_PROFILE"
    # Container credentials (ECS, CodeBuild)
    if env.get("AWS_CONTAINER_CREDENTIALS_RELATIVE_URI", "").strip():
        return "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"
    # Web identity (EKS IRSA)
    if env.get("AWS_WEB_IDENTITY_TOKEN_FILE", "").strip():
        return "AWS_WEB_IDENTITY_TOKEN_FILE"
    # No env vars — check if boto3 can resolve credentials via IMDS or other
    # implicit sources (EC2 instance role, ECS task role, Lambda, etc.)
    try:
        import botocore.session

        session = botocore.session.get_session()
        credentials = session.get_credentials()
        if credentials is not None:
            resolved = credentials.get_frozen_credentials()
            if resolved and resolved.access_key:
                return "iam-role"
    except Exception:
        pass
    return None


def has_aws_credentials(env: Mapping[str, str] | None = None) -> bool:
    """Return True if any AWS credential source is detected.

    Checks environment variables first (fast, no I/O), then falls back to
    boto3's credential chain which covers EC2 instance roles, ECS task roles,
    Lambda execution roles, and other IMDS-based sources that don't set
    environment variables.

    This two-tier approach mirrors the pattern from OpenClaw PR #62673:
    cloud environments (EC2, ECS, Lambda) provide credentials via instance
    metadata, not environment variables. The env-var check is a fast path
    for local development; the boto3 fallback covers all cloud deployments.
    """
    return resolve_aws_auth_env_var(env) is not None


def resolve_bedrock_region(env: Mapping[str, str] | None = None) -> str:
    """Resolve the AWS region for Bedrock API calls.

    Priority:
      1. AWS_REGION env var
      2. AWS_DEFAULT_REGION env var
      3. boto3/botocore configured region (from ~/.aws/config or SSO profile)
      4. us-east-1 (hard fallback)

    The boto3 fallback is critical for EU/AP users who configure their region
    in ~/.aws/config via a named profile rather than env vars — without it,
    live model discovery would always return us.* profile IDs regardless of
    the user's actual region.
    """
    env = env if env is not None else os.environ
    explicit = (
        env.get("AWS_REGION", "").strip() or env.get("AWS_DEFAULT_REGION", "").strip()
    )
    if explicit:
        return explicit
    try:
        import botocore.session

        region = botocore.session.get_session().get_config_variable("region")
        if region:
            return region
    except Exception:
        pass
    return "us-east-1"
