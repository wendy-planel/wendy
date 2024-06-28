import os
import asyncio

import aiodocker
import aiodocker.multiplexed
import aiodocker.utils
import structlog

from wendy import models, steamcmd
from wendy.constants import DeployStatus
from wendy.cluster import Cluster, ClusterWorld
from wendy.settings import DOCKER_URL, DEPLOYMENT_PATH


log = structlog.get_logger()
docker = aiodocker.Docker(DOCKER_URL)


def get_cluster_path(id: str) -> str:
    """获取存档目录路径.

    Args:
        id (str): 部署ID.

    Returns:
        str: 存档目录路径
    """
    return os.path.join(DEPLOYMENT_PATH, id)


def get_container_name(id: str, world: ClusterWorld) -> str:
    return f"dst_{world.name.lower()}_{id}"


async def update_mods(
    id: str,
    image: str,
    timeout: int = 30,
):
    container_name = f"dst_update_mods_{id}"
    file_path = get_cluster_path(id)
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
    container_name = get_container_name(id, world)
    file_path = get_cluster_path(id)
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
        "Tty": True,
        "OpenStdin": True,
    }
    container = await docker.containers.create_or_replace(
        name=container_name,
        config=config,
    )
    await container.restart()
    return container_name


async def deploy(
    cluster: Cluster,
):
    id = cluster.id
    cluster.containers.clear()
    image = await build(cluster.version)
    # 先更新模组
    await update_mods(id, image)
    # 部署主世界
    master = await deploy_world(id, image, cluster.master)
    cluster.containers.append(master)
    # 部署洞穴
    caves = await deploy_world(id, image, cluster.caves)
    cluster.containers.append(caves)


async def build(version: str) -> str:
    tag = f"ylei2023/dontstarvetogether:{version}"
    max_retry = 3
    while max_retry > 0:
        try:
            await docker.images.inspect(tag)
            return tag
        except Exception:
            log.info(f"开始拉取最新镜像: {tag}")
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


async def monitor():
    """当版本更新时，重新部署所有容器"""
    while True:
        try:
            version = await steamcmd.dst_version()
            log.info(f"[monitor] 最新镜像: {version}")
            async for item in models.Deploy.filter(status=DeployStatus.running.value):
                cluster = Cluster.model_validate(item.content)
                redeploy = False
                id = int(cluster.id)
                if cluster.version != version:
                    cluster.version = version
                    redeploy = True
                for container_name in cluster.containers:
                    try:
                        container = await docker.containers.get(container_name)
                        status = container._container.get("State", {}).get("Status")
                        redeploy |= status != "running"
                    except Exception:
                        redeploy = True
                if redeploy:
                    log.info(f"redeploy {id}")
                    await deploy(cluster)
                    await models.Deploy.filter(id=id).update(
                        content=cluster.model_dump()
                    )
        except Exception as e:
            log.exception(f"monitor error: {e}")
        finally:
            await asyncio.sleep(30 * 60)


async def attach(id: str, command: str, world: ClusterWorld):
    """控制台执行命令.

    Args:
        id (str): 存档ID.
        command (str): 命令.
        world (ClusterWorld): 世界.
    """
    container_name = get_container_name(id, world)
    container = await docker.containers.get(container_name)
    console = container.attach(stdout=True, stderr=True, stdin=True)
    async with console:
        await console.write_in(command.encode())


async def logs(id: str, world: ClusterWorld):
    container_name = get_container_name(id, world)
    container = await docker.containers.get(container_name)
    params = {"stdout": True, "stderr": False, "follow": False}
    cm = container.docker._query(
        "containers/{self._id}/logs".format(self=container),
        method="GET",
        params=params,
    )
    inspect_info = await container.show()
    is_tty = inspect_info["Config"]["Tty"]
    async with cm as response:
        logs_stream = aiodocker.utils._DecodeHelper(
            aiodocker.multiplexed.MultiplexedResult(response, raw=is_tty),
            encoding="utf-8",
        )
        line = ""
        async for piece in logs_stream:
            for ch in piece:
                if ch == "\n":
                    yield line.strip()
                    line = ""
                else:
                    line += ch
        if line:
            yield line.strip()
