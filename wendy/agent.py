import io
import os
import asyncio
import tarfile
from typing import Literal

import structlog
import aiodocker
import aiodocker.utils
import aiodocker.multiplexed

from wendy.cluster import Cluster
from wendy import models, steamcmd
from wendy.constants import DeployStatus
from wendy.settings import (
    DST_IMAGE,
    GAME_ARCHIVE_PATH,
    GAME_ARCHIVE_VOLUME,
)


log = structlog.get_logger()


def get_cluster_path(id: str) -> str:
    """获取存档目录路径.

    Args:
        id (str): 部署ID.

    Returns:
        str: 存档目录路径(在本容器中，非dst容器).
    """
    return os.path.join(GAME_ARCHIVE_PATH, id)


def get_container_name(
    id: str,
    world: Literal["Master", "Caves"],
) -> str:
    return f"dst_{world.lower()}_{id}"


def make_tarfile_in_memory(
    source_dir: str,
    arcname: str,
) -> io.BytesIO:
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        tar.add(source_dir, arcname=arcname)
    tar_stream.seek(0)
    return tar_stream


async def download_archive(
    id: str,
    docker: aiodocker.Docker,
):
    """上次存档到挂载卷.

    Args:
        id (str): 存档ID.
        docker (aiodocker.Docker): docker.

    """
    # 临时上传存档的容器
    container_name = f"dst_busybox_{id}"
    await pull("busybox:latest", docker)
    # 创建一个busybox容器
    target_path = "/home/steam/dst/archive"
    config = {
        "Image": "busybox:latest",
        "RestartPolicy": {"Name": "no"},
        "Cmd": ["sh", "-c", "while true; do sleep 3600; done"],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": f"{GAME_ARCHIVE_VOLUME}_{id}",
                    "Target": target_path,
                }
            ]
        },
    }
    busybox = await docker.containers.create_or_replace(container_name, config)
    await busybox.start()
    file = await busybox.get_archive(target_path)
    # 停止busybox容器
    await busybox.stop()
    return file


async def upload_archive(
    id: str,
    cluster_path: str,
    docker: aiodocker.Docker,
) -> str:
    """上次存档到挂载卷.

    Args:
        id (str): 存档ID.
        cluster_path (str): 存档路径.

    Returns:
        str: 有存档的挂载卷名.
    """
    # 临时上传存档的容器
    container_name = f"dst_busybox_{id}"
    await pull("busybox:latest", docker)
    # 创建挂载卷，重复创建不影响
    volume = f"{GAME_ARCHIVE_VOLUME}_{id}"
    volume_config = {
        "Name": volume,
        "Driver": "local",
        "DriverOpts": {},
        "Labels": {"wendy": "cute"},
    }
    await docker.volumes.create(volume_config)
    # 创建一个busybox容器
    target_path = "/home/steam/dst/"
    dst_folder = "archive"
    config = {
        "Image": "busybox:latest",
        "RestartPolicy": {"Name": "no"},
        "Cmd": ["sh", "-c", "while true; do sleep 3600; done"],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": volume,
                    "Target": os.path.join(target_path, dst_folder),
                }
            ]
        },
    }
    busybox = await docker.containers.create_or_replace(container_name, config)
    await busybox.start()
    # 将存档打包为tar并上传到挂载卷中
    tar_stream = make_tarfile_in_memory(cluster_path, dst_folder)
    await busybox.put_archive(target_path, tar_stream.read())
    # 停止busybox容器
    await busybox.stop()
    return volume


async def update_mods(
    id: str,
    image: str,
    volume: str,
    docker: aiodocker.Docker,
    timeout: int = 3000,
):
    container_name = f"dst_update_mods_{id}"
    # 不是很好的解决办法
    volumes = await docker.volumes.list()
    mount_point = None
    for item in volumes["Volumes"]:
        if item["Name"] == volume:
            mount_point = item["Mountpoint"]
    if mount_point is None:
        return
    config = {
        "Image": image,
        "RestartPolicy": {"Name": "no"},
        "Cmd": [
            "-only_update_server_mods",
            "-ugc_directory",
            "/home/steam/dst/game/ugc_mods",
        ],
        "HostConfig": {
            "Binds": [
                f"{mount_point}/mods:/home/steam/dst/game/mods",
                f"{mount_point}/ugc_mods:/home/steam/dst/game/ugc_mods",
            ],
            "NetworkMode": "host",
        },
    }
    container = await docker.containers.create_or_replace(
        name=container_name,
        config=config,
    )
    await container.start()
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
    volume: str,
    docker: aiodocker.Docker,
    world: Literal["Master", "Caves"],
):
    container_name = get_container_name(id, world)
    config = {
        "Image": image,
        "RestartPolicy": {"Name": "always"},
        "Cmd": [
            "-skip_update_server_mods",
            "-ugc_directory",
            "/home/steam/dst/archive/ugc_mods",
            "-persistent_storage_root",
            "/home/steam/dst",
            "-conf_dir",
            "archive",
            "-cluster",
            "Cluster_1",
            "-shard",
            world,
        ],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": volume,
                    "Target": "/home/steam/dst/archive",
                }
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
    await container.start()
    return container_name


async def deploy(cluster: Cluster):
    async with aiodocker.Docker(cluster.docker_api) as docker:
        id = cluster.id
        cluster.containers.clear()
        image = DST_IMAGE + ":" + cluster.version
        # 拉取镜像
        await pull(image, docker)
        # 生成存档配置
        cluster_path = get_cluster_path(cluster.id)
        cluster.save(cluster_path)
        # 上传存档到挂载卷
        volume = await upload_archive(cluster.id, cluster_path, docker)
        # 更新模组
        await update_mods(id, image, volume, docker)
        # 部署主世界
        master = await deploy_world(id, image, volume, docker, cluster.master.name)
        cluster.containers.append(master)
        # 部署洞穴
        if cluster.enable_caves:
            caves = await deploy_world(id, image, volume, docker, cluster.caves.name)
            cluster.containers.append(caves)


async def pull(image: str, docker: aiodocker.Docker) -> str:
    max_retry = 3
    while max_retry > 0:
        try:
            await docker.images.inspect(image)
            return image
        except Exception:
            await docker.images.pull(from_image=image)
            await asyncio.sleep(3)
        max_retry -= 1
    raise ValueError(f"image: {image} not found")


async def delete(cluster: Cluster):
    async with aiodocker.Docker(cluster.docker_api) as docker:
        for name in cluster.containers:
            try:
                container = await docker.containers.get(name)
                await container.stop()
                await container.delete()
            except Exception:
                pass


async def stop(cluster: Cluster):
    async with aiodocker.Docker(cluster.docker_api) as docker:
        for name in cluster.containers:
            try:
                container = await docker.containers.get(name)
                await container.stop()
            except Exception:
                pass


async def monitor():
    """当版本更新时，重新部署所有容器"""
    while True:
        try:
            async for item in models.Deploy.filter(
                status=DeployStatus.running.value,
            ):
                cluster = Cluster.model_validate(item.content)
                async with aiodocker.Docker(cluster.docker_api) as docker:
                    version = await steamcmd.dst_version()
                    log.info(f"[monitor] 最新镜像: {version}")
                    redeploy = False
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
                        log.info(f"redeploy {cluster.id}")
                        await deploy(cluster)
                        await models.Deploy.filter(id=int(cluster.id)).update(
                            content=cluster.model_dump(),
                        )
        except Exception as e:
            log.exception(f"monitor error: {e}")
        finally:
            await asyncio.sleep(60 * 60)


async def attach(
    command: str,
    world: Literal["master", "caves"],
    cluster: Cluster,
):
    """控制台执行命令.

    Args:
        command (str): 命令.
        world (Literal["master", "caves"]): 世界.
        cluster (Cluster): 存档.
    """
    container_name = get_container_name(cluster.id, world)
    async with aiodocker.Docker(cluster.docker_api) as docker:
        container = await docker.containers.get(container_name)
        console = container.attach(stdout=True, stderr=True, stdin=True)
        async with console:
            await console.write_in(command.encode())


async def logs(
    world: Literal["master", "caves"],
    cluster: Cluster,
):
    container_name = get_container_name(cluster.id, world)
    async with aiodocker.Docker(cluster.docker_api) as docker:
        container = await docker.containers.get(container_name)
        params = {
            "stdout": True,
            "stderr": False,
            "follow": False,
        }
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
