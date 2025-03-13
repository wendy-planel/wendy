import shutil
from typing import List

import io
import os
import uuid
import asyncio
import tarfile
import zipfile

import httpx
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
        await busybox.stop()
    return file


async def filter_downloaded_ugc_mods(
    mods: List[str],
    path: str,
    details: dict | None = None,
) -> List[str]:
    """过滤掉已下载且最新模组, 返回任需要下载的模组列表.

    Args:
        mods (List[str]): 模组列表.
        path (str): appworkshop_322330.acf同层级路径.
        details (dict | None): publishedfiledetails信息.

    Returns:
        List[str]: 过滤后任需要下载的模组列表.
    """
    if not mods:
        return []
    if details is None:
        details = await steamcmd.publishedfiledetails(mods)
    mods_info = {}
    downloaded = {}
    residue_mods = []
    for mod in details["response"]["publishedfiledetails"]:
        if time_updated := mod.get("time_updated"):
            mods_info[mod["publishedfileid"]] = str(time_updated)
    acf_file_path = os.path.join(path, "appworkshop_322330.acf")
    acf_mods_info = steamcmd.parse_mods_last_updated(acf_file_path)
    ugc_content_path = os.path.join(path, "content/322330")
    if os.path.exists(ugc_content_path):
        for mod_id in os.listdir(ugc_content_path):
            if mod_id in acf_mods_info:
                downloaded[mod_id] = acf_mods_info[mod_id]
    for mod_id in mods_info:
        if mod_id not in downloaded or (mods_info[mod_id] != downloaded[mod_id]):
            residue_mods.append(mod_id)
    return residue_mods


async def download_mods_by_fileurl(
    mods: List[str],
    path: str,
    details: dict | None = None,
) -> List[str]:
    """通过模组的详细信息接口返回的file_url下载模组.

    Args:
        mods (List[str]): 模组.
        path (str): mods路径.
        details (dict | None): publishedfiledetails信息.

    Returns:
        List[str]: 剩余未下载模组.
    """
    if not mods:
        return []
    if details is None:
        details = await steamcmd.publishedfiledetails(mods)
    ugc_mods = []
    fileurl_mods = []
    for mod in details["response"]["publishedfiledetails"]:
        mod_id = mod["publishedfileid"]
        if file_url := mod.get("file_url"):
            fileurl_mods.append((mod_id, file_url))
        else:
            ugc_mods.append(mod_id)
    target_path = os.path.join(path, f"workshop-{mod_id}")
    tmp_path = os.path.join(path, f"{mod_id}")
    async with httpx.AsyncClient(timeout=10) as client:
        for mod_id, file_url in fileurl_mods:
            if os.path.exists(target_path):
                continue
            for _ in range(3):
                try:
                    response = await client.get(file_url)
                    with zipfile.ZipFile(io.BytesIO(response.content), "r") as file:
                        members = file.namelist()
                        for member in members:
                            zipinfo = file.getinfo(member)
                            zipinfo.filename = zipinfo.filename.replace("\\", "/")
                            file._extract_member(zipinfo, tmp_path, None)
                    # 重命名文件夹
                    os.rename(tmp_path, target_path)
                    break
                except Exception:
                    import traceback

                    log.warning("download_mods_by_fileurl error")
                    log.warning(traceback.format_exc())
                    shutil.rmtree(tmp_path)
    return ugc_mods


async def download_mods_by_steamcmd(
    mods: List[str],
    path: str,
    details: dict,
    timeout: int = 3000,
):
    mods = await filter_downloaded_ugc_mods(mods, path, details)
    cmd = ["+login", "anonymous"]
    for mod_id in mods:
        cmd.extend(["+workshop_download_item", "322330", mod_id])
    cmd.append("+quit")
    image = "steamcmd/steamcmd:latest"
    container_name = f"dst_download_mods_{uuid.uuid4()}"
    async with aiodocker.Docker() as docker:
        await pull(image, docker)
        config = {
            "Image": image,
            "RestartPolicy": {"Name": "no"},
            "Cmd": cmd,
            "HostConfig": {
                "Binds": [
                    f"{path}:/root/.local/share/Steam/steamapps/workshop",
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


async def download_mods(
    mods: List[str],
    path: str,
) -> str:
    """下载MOD.

    Args:
        id (str | int): id.
        mods (List[str]): 模组列表.
        path (str): 挂载路径.
        timeout (int, optional): 超时.

    Returns:
        str: mods路径.
    """
    mod_path = os.path.join(path, "mods")
    ugc_path = os.path.join(path, "ugc_mods")
    if not os.path.exists(mod_path):
        os.makedirs(mod_path)
    if not os.path.exists(ugc_path):
        os.makedirs(ugc_path)
    if not mods:
        return mod_path
    details = await steamcmd.publishedfiledetails(mods)
    if mods:
        ugc_mods = await download_mods_by_fileurl(mods, mod_path, details)
    if ugc_mods:
        await download_mods_by_steamcmd(ugc_mods, ugc_path, details)
    return mod_path, ugc_path


async def upload(
    id: str | int,
    path: str,
    docker: aiodocker.Docker,
    volume_name: str,
):
    """上传文件到挂载卷.

    Args:
        id (str | int): id.
        archive_path (str): 存档路径.
        docker (aiodocker.Docker): docker.
        volume_name (str): 挂载卷名.

    Returns:
        str: 挂载卷名.
    """
    await pull("busybox:latest", docker)
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
                    "Target": path,
                }
            ]
        },
    }
    busybox = await docker.containers.create_or_replace(volume_name, config)
    await busybox.start()
    tar_stream = make_tarfile_in_memory(path)
    await busybox.put_archive(path, tar_stream.read())
    await busybox.stop()
    return volume_name


async def upload_archive(
    id: str | int,
    archive_path: str,
    docker: aiodocker.Docker,
) -> str:
    return await upload(id, archive_path, docker, f"wendy_{id}")


async def upload_mods(
    id: str | int,
    mods_path: str,
    docker: aiodocker.Docker,
):
    return await upload(id, mods_path, docker, f"wendy_mods_{id}")


async def upload_ugc_mods(
    id: str | int,
    ugc_path: str,
    docker: aiodocker.Docker,
):
    return await upload(id, ugc_path, docker, f"wendy_ugc_{id}")


async def deploy_world(
    container_name: str,
    image: str,
    archive_volume: str,
    mods_volume: str,
    ugc_volume: str,
    docker: aiodocker.Docker,
    world: ClusterWorld,
):
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
            "Cluster_1",
            "-shard",
            world.type,
        ],
        "HostConfig": {
            "Mounts": [
                {
                    "Type": "volume",
                    "Source": archive_volume,
                    "Target": "/home/steam/dst/save/Cluster_1",
                },
                {
                    "Type": "volume",
                    "Source": mods_volume,
                    "Target": "/home/steam/dst/game/mods",
                },
                {
                    "Type": "volume",
                    "Source": ugc_volume,
                    "Target": "/home/steam/dst/game/ugc_mods",
                },
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
    # TODO 这样自动生成端口有问题, 当ID超过600多的时候会超出端口范围
    port = 10000 + id * 100
    if cluster.ini.master_port == -1:
        cluster.ini.master_port = port
    for world in cluster.world:
        if world.server_port == -1:
            world.server_port = port + 1
        if world.master_server_port == -1:
            world.master_server_port = port + 2
        if world.authentication_port == -1:
            world.authentication_port = port + 3
        port += 3
    archive_path = get_archive_path(id)
    cluster.save(archive_path)
    await download_mods(cluster.mods, archive_path)
    for index, world in enumerate(cluster.world):
        async with aiodocker.Docker(world.docker_api) as docker:
            image = DST_IMAGE + ":" + version
            world.container = f"dst_{world.type.lower()}_{id}_{index}"
            await pull(image, docker)
            archive_volume = await upload_archive(id, f"{archive_path}/Cluster_1", docker)
            mods_volume = await upload_mods(id, f"{archive_path}/mods", docker)
            ugc_volume = await upload_ugc_mods(id, f"{archive_path}/ugc_mods", docker)
            await deploy_world(
                world.container,
                image,
                archive_volume,
                mods_volume,
                ugc_volume,
                docker,
                world,
            )
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
        if world.version != version:
            log.info(f"cluster {id} update version: {version}")
            return True
        async with aiodocker.Docker(world.docker_api) as docker:
            try:
                container = await docker.containers.get(world.container)
                status = container._container.get("State", {}).get("Status")
                assert status == "running"
            except Exception:
                log.info(f"cluster {id} status exception redeploy")
                return True
    if not cluster.mods:
        return False
    ugc = []
    archive_path = get_archive_path(id)
    mods_path = cluster.mods_path(archive_path)
    ugc_mods_path = cluster.ugc_mods_path(archive_path)
    for mod in cluster.mods:
        downloaded = False
        for mod_dir in os.listdir(mods_path):
            if mod in mod_dir:
                downloaded = True
                break
        if not downloaded:
            ugc.append(mod)
    if mods := await filter_downloaded_ugc_mods(ugc, ugc_mods_path):
        log.info(f"cluster {id} update mods: {mods}")
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
                cluster = await deploy(item.id, cluster, version=version)
                await models.Deploy.filter(id=item.id).update(cluster=cluster.model_dump())
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
