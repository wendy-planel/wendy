from typing import Literal, List

import io
import os
import asyncio
import tarfile

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


def get_cluster_path(id: str | int) -> str:
    """获取存档目录路径.

    Args:
        id (str | int): 部署ID.

    Returns:
        str: 存档目录路径(在本容器中，非dst容器).
    """
    return os.path.join(GAME_ARCHIVE_PATH, str(id))


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
    docker_api: str,
):
    """下载存档.

    Args:
        id (str): id.
        docker_api (str): docker.
    """
    async with aiodocker.Docker(docker_api) as docker:  # 临时上传存档的容器
        # 临时上传存档的容器
        container_name = f"wendy_busybox_{id}"
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


async def download_mods(
    id: str | int,
    mods: List[str],
    cluster_path: str,
    timeout: int = 3000,
):
    if not mods:
        return
    container_name = f"dst_download_mods_{id}"
    image = "steamcmd/steamcmd:latest"
    mount_point = os.path.join(cluster_path, "ugc_mods")
    cmd = ["+login", "anonymous"]
    for mod_id in mods:
        cmd.extend(["+workshop_download_item", "322330", mod_id])
    cmd.append("+quit")
    async with aiodocker.Docker() as docker:
        await pull(image, docker)
        config = {
            "Image": "steamcmd/steamcmd:latest",
            "RestartPolicy": {"Name": "no"},
            "Cmd": cmd,
            "HostConfig": {
                "Binds": [
                    f"{mount_point}:/root/.local/share/Steam/steamapps/workshop",
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
    ugc_mods = os.listdir(os.path.join(mount_point, "content/322330"))
    for mod_id in mods:
        if mod_id not in ugc_mods:
            raise ValueError(f"mod: {mod_id} download fail")


async def upload_archive(
    id: str | int,
    cluster_path: str,
    docker: aiodocker.Docker,
) -> str:
    """上传存档到挂载卷.

    Args:
        id (str | int): id.
        cluster_path (str): 存档路径.
        docker (aiodocker.Docker): docker.

    Returns:
        str: 挂载卷名.
    """
    # 临时上传存档的容器
    container_name = f"wendy_busybox_{id}"
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


async def deploy_world(
    id: str | int,
    image: str,
    volume: str,
    docker: aiodocker.Docker,
    type: Literal["Master", "Caves"],
):
    container_name = f"dst_{type.lower()}_{id}"
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
            type,
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


async def deploy(
    id: int,
    cluster: Cluster,
    version: str | None = None,
) -> Cluster:
    if version is None:
        version = await steamcmd.dst_version()
    port = 10000 + id * 100
    cluster.ini.master_port = port
    for world in cluster.world:
        world.server_port = port + 1
        world.master_server_port = port + 2
        world.authentication_port = port + 3
        port += 3
    cluster_path = get_cluster_path(id)
    cluster.save(cluster_path)
    await download_mods(id, cluster.mods, cluster_path)
    for world in cluster.world:
        async with aiodocker.Docker(world.docker_api) as docker:
            image = DST_IMAGE + ":" + version
            await pull(image, docker)
            volume = await upload_archive(id, cluster_path, docker)
            world.container = await deploy_world(id, image, volume, docker, world.type)
            world.version = version
    return cluster


async def pull(image: str, docker: aiodocker.Docker) -> str:
    max_retry = 3
    while max_retry > 0:
        try:
            await docker.images.inspect(image)
            return image
        except Exception:
            log.info(f"拉取镜像：{image}")
            await docker.images.pull(from_image=image)
            await asyncio.sleep(3)
        max_retry -= 1
    raise ValueError(f"image: {image} not found")


async def delete(cluster: Cluster):
    for world in cluster.world:
        async with aiodocker.Docker(world.docker_api) as docker:
            try:
                container = await docker.containers.get(world.container)
                await container.stop()
                await container.delete()
            except Exception:
                pass


async def stop(cluster: Cluster):
    for world in cluster.world:
        async with aiodocker.Docker(world.docker_api) as docker:
            try:
                container = await docker.containers.get(world.container)
                await container.stop()
            except Exception:
                pass


async def redeploy(
    cluster: Cluster,
    version: str | None = None,
) -> bool:
    """检测是否需要重新部署.

    Args:
        cluster (Cluster): cluster.
        version (str | None, optional): 最新版本.

    Returns:
        bool: True 需要重新部署.
    """
    if version is None:
        version = await steamcmd.dst_version()
    for world in cluster.world:
        # 版本更新需要重新部署
        if world.version != version:
            return True
        async with aiodocker.Docker(world.docker_api) as docker:
            try:
                container = await docker.containers.get(world.container)
                status = container._container.get("State", {}).get("Status")
                # 状态异常需要重新部署
                assert status == "running"
            except Exception:
                return True
    if not cluster.mods:
        return False
    # 模组更新检测
    mods_info = await steamcmd.mods_last_updated(cluster.mods)
    acf_file_path = os.path.join(
        get_cluster_path(cluster.id),
        "ugc_mods/appworkshop_322330.acf",
    )
    current_mods_info = steamcmd.parse_mods_last_updated(acf_file_path)
    for mod_id in cluster.mods:
        if mod_id not in mods_info or mod_id not in current_mods_info:
            log.warning(f"cluster {cluster.id} mod {mod_id} not found")
            return True
        if mods_info[mod_id] != current_mods_info[mod_id]:
            log.info(f"cluster {cluster.id} mod {mod_id} update")
            return True
    return False


async def monitor():
    """当版本更新时，重新部署所有容器"""
    while True:
        try:
            version = await steamcmd.dst_version()
            log.info(f"[monitor] 最新镜像: {version}")
            running = DeployStatus.running.value
            async for item in models.Deploy.filter(status=running):
                cluster = Cluster.model_validate(item.cluster)
                if not await redeploy(cluster, version):
                    continue
                log.info(f"redeploy {item.id}: {version}")
                cluster = await deploy(item.id, cluster, version=version)
                await models.Deploy.filter(id=item.id).update(
                    cluster=cluster.model_dump()
                )
        except Exception as e:
            log.exception(f"monitor error: {e}")
        finally:
            await asyncio.sleep(60 * 60)


async def attach(
    command: str,
    docker_api: str,
    container_name: str,
):
    """控制台执行命令.

    Args:
        command (str): 命令.
        docker_api (str): DOCKER API.
        container_name (str): 容器名.
    """
    async with aiodocker.Docker(docker_api) as docker:
        container = await docker.containers.get(container_name)
        console = container.attach(stdout=True, stderr=True, stdin=True)
        async with console:
            await console.write_in(command.encode())


async def logs(
    docker_api: str,
    container_name: str,
):
    async with aiodocker.Docker(docker_api) as docker:
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
