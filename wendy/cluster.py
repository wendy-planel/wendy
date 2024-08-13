from typing import Literal, List

import re
import os
import configparser

from pydantic import BaseModel

from wendy.settings import DOCKER_API_DEFAULT
from wendy.constants import (
    modoverrides_default,
    caves_leveldataoverride_default,
    master_leveldataoverride_default,
)


class ClusterWorld(BaseModel):
    leveldataoverride: str
    modoverrides: str
    # server.ini文件配置内容
    # [SHARD]
    id: str
    name: str
    is_master: bool
    # [NETWORK]
    server_port: int = -1
    # [STEAM]
    master_server_port: int = -1
    authentication_port: int = -1
    # [ACCOUNT]
    encode_user_path: bool = True
    # 部署配置
    type: Literal["Master", "Caves"]
    version: str = ""
    docker_api: str
    container: str = ""

    def save(self, path: str):
        path = os.path.join(path, self.name)
        # 创建目录
        if not os.path.exists(path):
            os.makedirs(path)
        # 写入leveldataoverride.lua
        with open(os.path.join(path, "leveldataoverride.lua"), "w") as file:
            file.write(self.leveldataoverride)
        # 写入modoverrides.lua
        with open(os.path.join(path, "modoverrides.lua"), "w") as file:
            file.write(self.modoverrides)
        # 写入server.ini
        lines = [
            "[SHARD]\n",
            f"id = {self.id}\n",
            f"name = {self.name}\n",
            f"is_master = {'true' if self.is_master else 'false'}\n",
            "\n[NETWORK]\n",
            f"server_port = {self.server_port}\n",
            "\n[STEAM]\n",
            f"master_server_port = {self.master_server_port}\n",
            f"authentication_port = {self.authentication_port}\n",
            "\n[ACCOUNT]\n",
            f"encode_user_path = {'true' if self.encode_user_path else 'false'}\n",
        ]
        with open(os.path.join(path, "server.ini"), "w") as file:
            file.writelines(lines)

    @classmethod
    def load_from_file(
        cls,
        path: str,
        type: Literal["Master", "Caves"],
        docker_api: str,
    ) -> "ClusterWorld":
        path = os.path.join(path, type)
        with open(os.path.join(path, "leveldataoverride.lua"), "r") as file:
            leveldataoverride = file.read()
        with open(os.path.join(path, "modoverrides.lua"), "r") as file:
            modoverrides = file.read()
        is_master = type == "Master"
        id = "1" if is_master else "2"
        return cls(
            leveldataoverride=leveldataoverride,
            modoverrides=modoverrides,
            id=id,
            name=type,
            is_master=is_master,
            type=type,
            docker_api=docker_api,
        )


class ClusterIni(BaseModel):
    # [GAMEPLAY]
    game_mode: Literal["survival", "endless", "wilderness"] = "endless"
    max_players: int = 6
    pvp: bool = False
    pause_when_empty: bool = True
    vote_enabled: bool = False
    # [NETWORK]
    lan_only_cluster: bool = False
    cluster_password: str = ""
    cluster_description: str = ""
    cluster_name: str
    offline_cluster: bool = False
    cluster_language: str = "zh"
    # [MISC]
    console_enabled: bool = True
    # [SHARD]
    shard_enabled: bool = True
    bind_ip: str = "127.0.0.1"
    master_ip: str = "127.0.0.1"
    master_port: int = -1
    cluster_key: str = "defaultPass"

    def save(self, path: str):
        lines = [
            "[GAMEPLAY]\n",
            f"game_mode = {self.game_mode}\n",
            f"max_players = {self.max_players}\n",
            f"pvp = {'true' if self.pvp else 'false'}\n",
            f"pause_when_empty = {'true' if self.pause_when_empty else 'false'}\n",
            f"vote_enabled = {'true' if self.vote_enabled else 'false'}\n",
            "\n[NETWORK]\n",
            f"lan_only_cluster = {'true' if self.lan_only_cluster else 'false'}\n",
            f"cluster_password = {self.cluster_password}\n",
            f"cluster_description = {self.cluster_description}\n",
            f"cluster_name = {self.cluster_name}\n",
            f"offline_cluster = {'true' if self.offline_cluster else 'false'}\n",
            f"cluster_language = {self.cluster_language}\n",
            "\n[MISC]\n",
            f"console_enabled = {'true' if self.console_enabled else 'false'}\n",
            "\n[SHARD]\n",
            f"shard_enabled = {'true' if self.shard_enabled else 'false'}\n",
            f"bind_ip = {self.bind_ip}\n",
            f"master_ip = {self.master_ip}\n",
            f"master_port = {self.master_port}\n",
            f"cluster_key = {self.cluster_key}\n",
        ]
        with open(os.path.join(path, "cluster.ini"), "w") as file:
            file.writelines(lines)

    @classmethod
    def _parse(cls, k: str, v: str):
        if v == "true":
            v = True
        elif v == "false":
            v = False
        int_fields = {"max_players", "master_port"}
        if k in int_fields:
            v = int(v)
        return v

    @classmethod
    def load_from_file(cls, file_path: str) -> "ClusterIni":
        config = configparser.ConfigParser()
        config.read(file_path)
        config = config._sections
        data = dict()
        data.update(config.get("GAMEPLAY", {}))
        data.update(config.get("NETWORK", {}))
        data.update(config.get("MISC", {}))
        data.update(config.get("SHARD", {}))
        for k, v in data.items():
            data[k] = cls._parse(k, v)
        return cls(**data)


class Cluster(BaseModel):
    cluster_token: str
    ini: ClusterIni = ClusterIni(cluster_name="Wendy Cute", master_port=10888)
    world: List[ClusterWorld] = [
        ClusterWorld(
            id="1",
            name="Master",
            type="Master",
            leveldataoverride=master_leveldataoverride_default,
            modoverrides=modoverrides_default,
            is_master=True,
            server_port=10999,
            master_server_port=27016,
            authentication_port=8766,
            docker_api=DOCKER_API_DEFAULT,
        ),
        ClusterWorld(
            id="2",
            name="Caves",
            type="Caves",
            is_master=False,
            server_port=10999,
            master_server_port=27017,
            authentication_port=8767,
            docker_api=DOCKER_API_DEFAULT,
            modoverrides=modoverrides_default,
            leveldataoverride=caves_leveldataoverride_default,
        ),
    ]

    def save_mods_setup(self, mods_path: str):
        for world in self.world:
            mods = set(re.findall(r"workshop-([0-9]+)", world.modoverrides))
            filename = "dedicated_server_mods_setup.lua"
            if mods:
                with open(os.path.join(mods_path, filename), "w") as file:
                    for mod_id in mods:
                        line = f'ServerModSetup("{mod_id}")\n'
                        file.write(line)

    def save(self, path: str):
        mods_path = os.path.join(path, self.mods_dir)
        if not os.path.exists(mods_path):
            os.makedirs(mods_path)
        self.save_mods_setup(mods_path)
        ugc_mods_path = os.path.join(path, self.ugc_mods_dir)
        if not os.path.exists(ugc_mods_path):
            os.makedirs(ugc_mods_path)
        cluster_dir = os.path.join(path, self.cluster_dir)
        if not os.path.exists(cluster_dir):
            os.makedirs(cluster_dir)
        self.ini.save(cluster_dir)
        # 写入cluster_token.txt
        with open(os.path.join(cluster_dir, "cluster_token.txt"), "w") as file:
            file.write(self.cluster_token)
        # 世界配置
        for world in self.world:
            world.save(cluster_dir)

    @property
    def mods_dir(self):
        return "mods"

    @property
    def ugc_mods_dir(self):
        return "ugc_mods"

    @property
    def cluster_dir(self):
        return "Cluster_1"

    @classmethod
    def create_from_dir(
        cls,
        cluster_path: str,
        docker_api: str,
    ) -> "Cluster":
        with open(os.path.join(cluster_path, "cluster_token.txt"), "r") as file:
            cluster_token = file.read()
        ini = ClusterIni.load_from_file(os.path.join(cluster_path, "cluster.ini"))
        master = ClusterWorld.load_from_file(cluster_path, "Master", docker_api)
        caves = ClusterWorld.load_from_file(cluster_path, "Caves", docker_api)
        return cls(
            cluster_token=cluster_token,
            ini=ini,
            world=[master, caves],
        )
