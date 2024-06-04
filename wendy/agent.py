import os
import asyncio

import aiodocker
import structlog

from wendy.cluster import Cluster, ClusterWorld
from wendy.settings import (
    DOCKER_URL,
    DOCKER_VOLUME,
    DOCKERFILE_PATH,
)


log = structlog.get_logger()
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


async def deploy_world(
    id: str,
    image: str,
    world: ClusterWorld,
):
    name = world.name
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
    }
    container = await docker.containers.create_or_replace(
        name=container_name,
        config=config,
    )
    await container.restart()
    return container_name


async def deploy(
    id: str,
    cluster: Cluster,
):
    image = await build(cluster.version)
    # 先更新模组
    container_name = await update_mods(id, image)
    cluster.containers.append(container_name)
    # 部署主世界
    container_name = await deploy_world(id, image, cluster.master)
    cluster.containers.append(container_name)
    # 部署洞穴
    container_name = await deploy_world(id, image, cluster.caves)
    cluster.containers.append(container_name)


async def build(version: str) -> str:
    tag = f"dontstarvetogether:{version}"
    buildargs = {"DST_BRANCH": version}
    max_count = 8
    while max_count > 0:
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
        except Exception as e:
            log.exception(f"build image {tag} error: {e}")
        finally:
            await asyncio.sleep(3)
            max_count -= 1
    if max_count == 0:
        return "superjump22/dontstarvetogether:latest"
    else:
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
