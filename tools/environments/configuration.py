"""Pure configuration mapping shared by terminal and file-tool sandboxes."""

import copy
from typing import Any


def environment_creation_options(
    config: dict[str, Any],
    overrides: dict[str, Any],
    *,
    task_id: str,
    timeout: int | None = None,
) -> dict[str, Any]:
    env_type = config["env_type"]
    image = ""
    if env_type in {"docker", "singularity", "modal", "daytona"}:
        image_key = f"{env_type}_image"
        image = overrides.get(image_key) or config[image_key]
    ssh = None
    if env_type == "ssh":
        ssh = {
            "host": config.get("ssh_host", ""),
            "user": config.get("ssh_user", ""),
            "port": config.get("ssh_port", 22),
            "key": config.get("ssh_key", ""),
            "persistent": config.get("ssh_persistent", False),
        }
    container = None
    if env_type in {"docker", "singularity", "modal", "daytona", "vercel_sandbox"}:
        defaults = {
            "container_cpu": 1,
            "container_memory": 5120,
            "container_disk": 51200,
            "container_persistent": True,
            "modal_mode": "auto",
            "vercel_runtime": "",
            "docker_volumes": [],
            "docker_mount_cwd_to_workspace": False,
            "docker_forward_env": [],
            "docker_env": {},
            "docker_run_as_host_user": False,
            "docker_extra_args": [],
        }
        container = {
            key: copy.deepcopy(config.get(key, default))
            for key, default in defaults.items()
        }
    return {
        "env_type": env_type,
        "image": image,
        "cwd": overrides.get("cwd") or config["cwd"],
        "timeout": config["timeout"] if timeout is None else timeout,
        "ssh_config": ssh,
        "container_config": container,
        "local_config": {"persistent": config.get("local_persistent", False)}
        if env_type == "local"
        else None,
        "task_id": task_id,
        "host_cwd": config.get("host_cwd"),
    }
