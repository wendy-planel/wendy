from typing import List

import os
import asyncio

import aiodocker
import structlog

from wendy import models, steamcmd
from wendy.constants import DeployStatus
from wendy.cluster import Cluster, ClusterWorld
from wendy.settings import DOCKER_URL, DEPLOYMENT_PATH


log = structlog.get_logger()
docker = aiodocker.Docker(DOCKER_URL)


async def update_mods(
    id: str,
    image: str,
    timeout: int = 30,
):
    container_name = f"dst_update_mods_{id}"
    file_path = os.path.join(DEPLOYMENT_PATH, id)
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
    file_path = os.path.join(DEPLOYMENT_PATH, id)
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
    tag = f"ylei2023/dontstarvetogether:{version}"
    max_retry = 3
    while max_retry > 0:
        try:
            await docker.images.inspect(tag)
            return tag
        except Exception:
            await docker.images.pull(from_image=tag)
            await asyncio.sleep(3)
        max_retry -= 1
    raise ValueError(f"image: {tag} not found")


async def delete(cluster: Cluster):
    for name in cluster.containers:
        container = await docker.containers.get(name)
        await container.stop()
        await container.delete()


async def stop(cluster: Cluster):
    for name in cluster.containers:
        container = await docker.containers.get(name)
        await container.stop()


def get_deploy_id(names: List[str]) -> int:
    for name in names:
        if "dst" in name:
            return int(name.split("_")[-1])
    return -1


async def monitor():
    """当版本更新时，重新部署所有容器"""
    while True:
        try:
            log.info("monitor dst containers")
            version = await steamcmd.dst_version()
            containers = await docker.containers.list()
            # 记录部署ID
            dst = set()
            for container in containers:
                names = container._container.get("Names", [])
                if (deploy_id := get_deploy_id(names)) != -1:
                    dst.add(deploy_id)
            dpy_queryset = await models.Deploy.all()
            dpy_map = {dpy.id: dpy for dpy in dpy_queryset}
            # 读取部署
            for id in dst:
                if id in dpy_map:
                    dpy = dpy_map.pop(id)
                    cluster = Cluster.model_validate(dpy.content)
                    if dpy.status != DeployStatus.stop and cluster.version != version:
                        cluster.version = version
                        await deploy(id, cluster)
                        dpy.status = DeployStatus.running
                        dpy.content = cluster.model_dump()
                        await dpy.save()
                else:
                    log.warning(f"deploy {id} running not managed")
            # 未启动的容器重新启动
            for id in dpy_map:
                dpy = dpy_map[id]
                if dpy.status != DeployStatus.stop:
                    cluster = Cluster.model_validate(dpy.content)
                    cluster.version = version
                    await deploy(id, cluster)
                    dpy.status = DeployStatus.running
                    dpy.content = cluster.model_dump()
                    await dpy.save()
        except Exception as e:
            log.exception(f"monitor: {e}")
        finally:
            await asyncio.sleep(30 * 60)
