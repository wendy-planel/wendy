from typing import List, Tuple

import os
import asyncio

import yaml
import aiodocker

from wendy.cluster import Cluster, ClusterWorld
from wendy.settings import (
    DOCKER_URL,
    DOCKER_VOLUME,
    DOCKERFILE_PATH,
    DOCKGE_STACKS_PATH,
)


docker = aiodocker.Docker(DOCKER_URL)


async def get_volume_path(id: str):
    volumes = await docker.volumes.list()
    for volume in volumes["Volumes"]:
        if volume["Name"] == DOCKER_VOLUME:
            return os.path.join(volume["Mountpoint"], id)
    raise RuntimeError("not found volume")


async def update_mods(
    id: str,
    image: str,
    timeout: int = 30,
):
    container_name = f"dst_update_mods_{id}"
    file_path = await get_volume_path(id)
    config = {
        "Image": image,
        "RestartPolicy": {"Name": "no"},
        "Cmd": [
            "-only_update_server_mods",
            "-ugc_directory",
            "/home/steam/dst/game/ugc_mods",
            "-persistent_storage_root",
            "/home/steam/dst",
            "-conf_dir",
            "save",
            "-cluster",
            "cluster",
        ],
        "HostConfig": {
            "Binds": [
                f"{file_path}/Cluster_1:/home/steam/dst/save/cluster",
                f"{file_path}/mods:/home/steam/dst/game/mods",
                f"{file_path}/ugc_mods:/home/steam/dst/game/ugc_mods",
            ],
            "NetworkMode": "host",
        },
    }
    container = await docker.containers.create_or_replace(
        name=container_name,
        config=config,
    )
    await container.restart()
    while timeout > 0:
        container = await docker.containers.get(container_name)
        info = await container.show()
        if info["State"]["Status"] == "exited":
            break
        else:
            timeout -= 3
            await asyncio.sleep(3)
    return container_name


def save_docker_compose(id: str, services: List[Tuple[str, dict]]):
    docker_compose = {
        "version": "3.8",
        "services": {},
    }
    for container_name, config in services:
        docker_compose["services"][container_name] = {
            "image": config["Image"],
            "container_name": container_name,
            "restart": config["RestartPolicy"]["Name"],
            "command": config["Cmd"],
            "volumes": config["HostConfig"]["Binds"],
            "network_mode": config["HostConfig"]["NetworkMode"],
        }
    file_path = os.path.join(DOCKGE_STACKS_PATH, f"dst_{id}")
    if not os.path.exists(file_path):
        os.makedirs(file_path)
    file_path = os.path.join(file_path, "docker-compose.yml")
    with open(file_path, "w", encoding="utf-8") as file:
        yaml.dump(docker_compose, file, default_flow_style=False)


async def deploy_world(
    id: str,
    image: str,
    world: ClusterWorld,
):
    name = world.name
    health_check = {
        "Test": ["CMD", "nc", "-zuv", "127.0.0.1", str(world.ini.server_port)],
        "Interval": 2000000000,
        "Timeout": 30000000000,
        "StartPeriod": 300000000000,
    }
    container_name = f"dst_{name.lower()}_{id}"
    file_path = await get_volume_path(id)
    config = {
        "Image": image,
        "RestartPolicy": {"Name": "always"},
        "Cmd": [
            "-skip_update_server_mods",
            "-ugc_directory",
            "/home/steam/dst/game/ugc_mods",
            "-persistent_storage_root",
            "/home/steam/dst",
            "-conf_dir",
            "save",
            "-cluster",
            "cluster",
            "-shard",
            name,
        ],
        "HostConfig": {
            "Binds": [
                f"{file_path}/Cluster_1:/home/steam/dst/save/cluster",
                f"{file_path}/mods:/home/steam/dst/game/mods",
                f"{file_path}/ugc_mods:/home/steam/dst/game/ugc_mods",
            ],
            "NetworkMode": "host",
        },
        "Healthcheck": health_check,
    }
    container = await docker.containers.create_or_replace(
        name=container_name,
        config=config,
    )
    await container.restart()
    return container_name, config


async def deploy(
    id: str,
    cluster: Cluster,
):
    image = await build(cluster.version)
    services = []
    # 先更新模组
    container_name = await update_mods(id, image)
    cluster.containers.append(container_name)
    # 部署主世界
    container_name, config = await deploy_world(id, image, cluster.master)
    cluster.containers.append(container_name)
    services.append((container_name, config))
    # 部署洞穴
    container_name, config = await deploy_world(id, image, cluster.caves)
    cluster.containers.append(container_name)
    services.append((container_name, config))
    save_docker_compose(id, services)


async def build(version: str) -> str:
    tag = f"dontstarvetogether:{version}"
    buildargs = {"DST_BRANCH": version}
    while True:
        with open(DOCKERFILE_PATH, "rb") as file:
            await docker.images.build(
                fileobj=file,
                tag=tag,
                buildargs=buildargs,
                encoding="utf-8",
            )
        # 判单是否构建成功
        try:
            await docker.images.get(tag)
            break
        finally:
            await asyncio.sleep(3)
    return tag


async def delete(cluster: Cluster):
    for name in cluster.containers:
        container = await docker.containers.get(name)
        await container.stop()
        await container.delete()


async def stop(cluster: Cluster):
    for name in cluster.containers:
        container = await docker.containers.get(name)
        await container.stop()
