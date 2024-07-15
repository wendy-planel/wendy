from typing import Literal, List

import re
import os

from pydantic import BaseModel

from wendy.constants import CLUSTER_DEFAULT


class ClusterServerIni(BaseModel):
    # [SHARD]
    is_master: bool
    # [NETWORK]
    server_port: int
    # [STEAM]
    master_server_port: int
    authentication_port: int
    # [ACCOUNT]
    encode_user_path: bool = True

    def save(self, path: str):
        lines = [
            "[SHARD]\n",
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


class ClusterWorld(BaseModel):
    leveldataoverride: str
    modoverrides: str
    ini: ClusterServerIni
    name: Literal["Master", "Caves"]

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
        self.ini.save(path)


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
    master_port: int
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


class Cluster(BaseModel):
    id: str
    cluster_token: str
    ini: ClusterIni
    caves: ClusterWorld
    master: ClusterWorld
    ports: List[int]
    version: str
    containers: List[str] = []

    def save_mods_setup(self, mods_path: str):
        mods = set(re.findall(r"workshop-([0-9]+)", self.master.modoverrides))
        filename = "dedicated_server_mods_setup.lua"
        if mods:
            with open(os.path.join(mods_path, filename), "w") as file:
                for mod_id in mods:
                    line = f'ServerModSetup("{mod_id}")\n'
                    file.write(line)

    def save(self, path: str, enable_caves: bool = True):
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
        # 写入主世界配置
        self.master.save(cluster_dir)
        if enable_caves:
            # 写入洞穴配置
            self.caves.save(cluster_dir)

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
    def default(cls, id: str):
        return cls(id=id, **CLUSTER_DEFAULT)

    @classmethod
    def create_from_default(
        cls,
        id: str,
        bind_ip: str,
        master_ip: str,
        ports: List[int],
        version: str,
        game_mode: Literal["survival", "endless", "wilderness"],
        max_players: int,
        cluster_password: str,
        cluster_token: str,
        cluster_name: str,
        cluster_description: str,
        vote_enabled: bool,
        modoverrides: str,
        caves_leveldataoverride: str,
        master_leveldataoverride: str,
    ):
        # 基础配置
        cluster = cls.default(id)
        cluster.ports = ports
        cluster.version = version
        cluster.cluster_token = cluster_token
        # 洞穴配置
        cluster.caves.ini.server_port = ports[1]
        cluster.caves.ini.master_server_port = ports[2]
        cluster.caves.ini.authentication_port = ports[3]
        cluster.caves.modoverrides = modoverrides
        cluster.caves.leveldataoverride = caves_leveldataoverride
        # 主世界配置
        cluster.master.ini.server_port = ports[4]
        cluster.master.ini.master_server_port = ports[5]
        cluster.master.ini.authentication_port = ports[6]
        cluster.master.modoverrides = modoverrides
        cluster.master.leveldataoverride = master_leveldataoverride
        # 集群配置
        cluster.ini.bind_ip = bind_ip
        cluster.ini.master_ip = master_ip
        cluster.ini.master_port = ports[0]
        cluster.ini.game_mode = game_mode
        cluster.ini.max_players = max_players
        cluster.ini.cluster_password = cluster_password
        cluster.ini.cluster_name = cluster_name
        cluster.ini.vote_enabled = vote_enabled
        cluster.ini.cluster_description = cluster_description
        return cluster
