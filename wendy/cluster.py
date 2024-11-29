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
    # [SHARD]
    id: str = ""
    name: str = ""
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
        path = os.path.join(path, self.type)
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
            f"id = {self.id}\n" if self.id else "",
            f"name = {self.name}\n" if self.name else "",
            f"is_master = {self._dump_bool(self.is_master)}\n",
            "\n[NETWORK]\n",
            f"server_port = {self.server_port}\n",
            "\n[STEAM]\n",
            f"master_server_port = {self.master_server_port}\n",
            f"authentication_port = {self.authentication_port}\n",
            "\n[ACCOUNT]\n",
            f"encode_user_path = {self._dump_bool(self.encode_user_path)}\n",
        ]
        with open(os.path.join(path, "server.ini"), "w") as file:
            file.writelines(lines)

    @classmethod
    def _dump_bool(cls, value: bool) -> str:
        return "true" if value else "false"

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
        config = configparser.ConfigParser()
        config.read(os.path.join(path, "server.ini"))
        config = config._sections
        data = {}
        data.update(config.get("SHARD", {}))
        data.update(config.get("ACCOUNT", {}))
        return cls(
            leveldataoverride=leveldataoverride,
            modoverrides=modoverrides,
            type=type,
            docker_api=docker_api,
            **data,
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
    cluster_name: str = "Wendy Cute"
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
            f"pvp = {self._dump_bool(self.pvp)}\n",
            f"pause_when_empty = {self._dump_bool(self.pause_when_empty)}\n",
            f"vote_enabled = {self._dump_bool(self.vote_enabled)}\n",
            "\n[NETWORK]\n",
            f"lan_only_cluster = {self._dump_bool(self.lan_only_cluster)}\n",
            f"cluster_password = {self.cluster_password}\n",
            f"cluster_description = {self.cluster_description}\n",
            f"cluster_name = {self.cluster_name}\n",
            f"offline_cluster = {self._dump_bool(self.offline_cluster)}\n",
            f"cluster_language = {self.cluster_language}\n",
            "\n[MISC]\n",
            f"console_enabled = {self._dump_bool(self.console_enabled)}\n",
            "\n[SHARD]\n",
            f"shard_enabled = {self._dump_bool(self.shard_enabled)}\n",
            f"bind_ip = {self.bind_ip}\n",
            f"master_ip = {self.master_ip}\n",
            f"master_port = {self.master_port}\n",
            f"cluster_key = {self.cluster_key}\n",
        ]
        with open(os.path.join(path, "cluster.ini"), "w") as file:
            file.writelines(lines)

    @classmethod
    def _dump_bool(cls, value: bool) -> str:
        return "true" if value else "false"

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
    ini: ClusterIni = ClusterIni()
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

    @property
    def mods(self) -> List[str]:
        mods = set()
        for world in self.world:
            for mod_id in re.findall(r"workshop-([0-9]+)", world.modoverrides):
                mods.add(mod_id)
        return list(mods)

    @property
    def cluster_token_filename(self) -> str:
        return "cluster_token.txt"

    @property
    def mods_dirname(self) -> str:
        return "mods"

    @property
    def ugc_mods_dirname(self) -> str:
        return "ugc_mods"

    @property
    def cluster_dirname(self) -> str:
        return "Cluster_1"

    def save_mods_setup(self, mods_path: str):
        filename = "dedicated_server_mods_setup.lua"
        with open(os.path.join(mods_path, filename), "w") as file:
            for mod_id in self.mods:
                line = f'ServerModSetup("{mod_id}")\n'
                file.write(line)

    def save_ugc_mods(self, path: str) -> str:
        ugc_mods_path = os.path.join(path, self.ugc_mods_dirname)
        if not os.path.exists(ugc_mods_path):
            os.makedirs(ugc_mods_path)
        return ugc_mods_path

    def save_mods(self, path: str):
        mods_path = os.path.join(path, self.mods_dirname)
        if not os.path.exists(mods_path):
            os.makedirs(mods_path)
        self.save_mods_setup(mods_path)
        self.save_ugc_mods(path)

    def save_cluster_token(self, cluster_path: str) -> str:
        cluster_token_path = os.path.join(cluster_path, self.cluster_token_filename)
        with open(cluster_token_path, "w") as file:
            file.write(self.cluster_token)
        return cluster_token_path

    def save_cluster(self, path: str) -> str:
        cluster_path = os.path.join(path, self.cluster_dirname)
        if not os.path.exists(cluster_path):
            os.makedirs(cluster_path)
        self.ini.save(cluster_path)
        self.save_cluster_token(cluster_path)
        for world in self.world:
            world.save(cluster_path)
        return cluster_path

    def save(self, path: str):
        self.save_mods(path)
        self.save_cluster(path)

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
            ini=ini,
            world=[master, caves],
            cluster_token=cluster_token,
        )
