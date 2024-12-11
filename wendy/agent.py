from typing import List

import io
import os
import asyncio
import tarfile

import structlog
import aiodocker
import aiodocker.utils
import aiodocker.multiplexed

from wendy import models, steamcmd
from wendy.constants import DeployStatus
from wendy.cluster import Cluster, ClusterWorld
from wendy.settings import (
    DST_IMAGE,
    GAME_ARCHIVE_PATH,
)


log = structlog.get_logger()


def get_archive_path(id: str | int) -> str:
    """获取存档目录路径.

    Args:
        id (str | int): 部署ID.

    Returns:
        str: 存档目录路径(在本容器中，非dst容器).
    """
    return os.path.join(GAME_ARCHIVE_PATH, str(id))


def make_tarfile_in_memory(archive_path: str) -> io.BytesIO:
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        # Walk through all files and directories in the archive_path
        for root, _, files in os.walk(archive_path):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, start=archive_path)
                tar.add(file_path, arcname=arcname)
    tar_stream.seek(0)
    return tar_stream


async def download_archive(
    id: str | int,
    docker_api: str,
):
    """下载存档.

    Args:
        id (str | int): id.
        docker_api (str): docker.
    """
    async with aiodocker.Docker(docker_api) as docker:
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
                        "Source": f"wendy_{id}",
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
    mount_path: str,
    timeout: int = 3000,
) -> str:
    """下载MOD.

    Args:
        id (str | int): id.
        mods (List[str]): 模组列表.
        mount_path (str): 挂载路径.
        timeout (int, optional): 超时.

    Returns:
        str: ugc_mods路径.
    """
    if not mods:
        return
    container_name = f"dst_download_mods_{id}"
    image = "steamcmd/steamcmd:latest"
    cmd = ["+login", "anonymous"]
    for mod_id in mods:
        cmd.extend(["+workshop_download_item", "322330", mod_id])
    cmd.append("+quit")
    async with aiodocker.Docker() as docker:
        await pull(image, docker)
        config = {
            "Image": image,
            "RestartPolicy": {"Name": "no"},
            "Cmd": cmd,
            "HostConfig": {
                "Binds": [
                    f"{mount_path}:/root/.local/share/Steam/steamapps/workshop",
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
    await container.delete()
    ugc_mods_path = os.path.join(mount_path, "content/322330")
    ugc_mods = os.listdir(ugc_mods_path)
    for mod_id in mods:
        if mod_id not in ugc_mods:
            raise ValueError(f"mod: {mod_id} download fail")
    return ugc_mods_path


async def upload_archive(
    id: str | int,
    archive_path: str,
    docker: aiodocker.Docker,
) -> str:
    """上传存档到挂载卷.

    Args:
        id (str | int): id.
        archive_path (str): 存档路径.
        docker (aiodocker.Docker): docker.

    Returns:
        str: 挂载卷名.
    """
    container_name = f"wendy_busybox_{id}"
    await pull("busybox:latest", docker)
    volume_name = f"wendy_{id}"
    volume_config = {
        "Name": volume_name,
        "Driver": "local",
        "DriverOpts": {},
        "Labels": {"wendy": "cute"},
    }
    await docker.volumes.create(volume_config)
    config = {
        "Image": "busybox:latest",
        "RestartPolicy": {"Name": "no"},
        "Cmd": ["sh", "-c", "timeout 3600 sh -c 'while true; do sleep 3600; done'"],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": volume_name,
                    "Target": archive_path,
                }
            ]
        },
    }
    busybox = await docker.containers.create_or_replace(container_name, config)
    await busybox.start()
    tar_stream = make_tarfile_in_memory(archive_path)
    await busybox.put_archive(archive_path, tar_stream.read())
    await busybox.stop()
    return volume_name


async def deploy_world(
    id: str | int,
    image: str,
    volume_name: str,
    docker: aiodocker.Docker,
    world: ClusterWorld,
):
    container_name = f"dst_{world.name.lower()}_{id}"
    target_path = "/home/steam/dst/save"
    config = {
        "Image": image,
        "RestartPolicy": {"Name": "always"},
        "Cmd": [
            "-skip_update_server_mods",
            "-ugc_directory",
            f"{target_path}/ugc_mods",
            "-persistent_storage_root",
            "/home/steam/dst",
            "-conf_dir",
            "save",
            "-cluster",
            "Cluster_1",
            "-shard",
            world.type,
        ],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": volume_name,
                    "Target": target_path,
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
    if cluster.ini.master_port == -1:
        cluster.ini.master_port = port
    for world in cluster.world:
        world.server_port = port + 1
        world.master_server_port = port + 2
        world.authentication_port = port + 3
        port += 3
    archive_path = get_archive_path(id)
    cluster.save(archive_path)
    ugc_mods_path = cluster.save_ugc_mods(archive_path)
    await download_mods(id, cluster.mods, ugc_mods_path)
    for world in cluster.world:
        async with aiodocker.Docker(world.docker_api) as docker:
            image = DST_IMAGE + ":" + version
            await pull(image, docker)
            volume_name = await upload_archive(id, archive_path, docker)
            world.container = await deploy_world(id, image, volume_name, docker, world)
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
    id: int,
    cluster: Cluster,
    version: str | None = None,
) -> bool:
    """检测是否需要重新部署.

    Args:
        id (int): ID.
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
        get_archive_path(id),
        "ugc_mods/appworkshop_322330.acf",
    )
    current_mods_info = steamcmd.parse_mods_last_updated(acf_file_path)
    for mod_id in cluster.mods:
        if mod_id not in mods_info or mod_id not in current_mods_info:
            log.warning(f"cluster {id} mod {mod_id} not found")
            return True
        if mods_info[mod_id] != current_mods_info[mod_id]:
            log.info(f"cluster {id} mod {mod_id} update")
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
                if not await redeploy(item.id, cluster, version):
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
