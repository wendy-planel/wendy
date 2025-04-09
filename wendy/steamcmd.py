from typing import List, Dict

import os
import time

import httpx
import asyncio
import aiodocker

from wendy.settings import STEAM_API_KEY, DST_IMAGE


cache = {}
buildid = ""
cache_lock = asyncio.Lock()
buildid_lock = asyncio.Lock()


async def dst_version() -> str:
    """获取dst版本号.

    Returns:
        str: dst版本号.
    """
    async with buildid_lock:
        global buildid
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("https://api.steamcmd.net/v1/info/343050")
                buildid = response.json()["data"]["343050"]["depots"]["branches"]["public"]["buildid"]
        except Exception:
            async with aiodocker.Docker() as docker:
                images = await docker.images.list()
                tag_max = 0
                for item in images:
                    for tag in item["RepoTags"]:
                        if DST_IMAGE in tag:
                            tag_max = max(tag_max, int(tag.split(":")[-1]))
                if tag_max:
                    buildid = str(tag_max)
        return buildid


async def publishedfiledetails(mods: List[str]) -> dict:
    global cache
    mods.sort()
    key = ",".join(mods)
    now = int(time.time())
    async with cache_lock:
        for item in list(cache.keys()):
            if (now - cache[item][0]) > 1800:
                cache.pop(item)
        if key in cache:
            return cache[key][1]
        url = "http://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
        post_data = {"itemcount": len(mods)}
        for i in range(len(mods)):
            post_data[f"publishedfileids[{i}]"] = mods[i]
        async with httpx.AsyncClient() as client:
            response = await client.post(url, data=post_data)
        data = response.json()
        cache[key] = [now, data]
        return data


def parse_acf_file(acf_file_path: str) -> Dict[str, str]:
    """解析acf文件获取模组最后一次更新时间.

    Args:
        acf_file_path (str): acf文件.

    Returns:
        Dict[str, str]: {"模组ID": "最后一次更新时间"}.
    """
    if not os.path.exists(acf_file_path):
        return {}
    with open(acf_file_path, "r") as file:
        file_content = file.read()
    lines = file_content.splitlines()
    stack = [{}]
    current_key = None
    for line in lines:
        line = line.strip()
        if line == "{":
            new_dict = {}
            stack[-1][current_key] = new_dict
            stack.append(new_dict)
        elif line == "}":
            stack.pop()
        else:
            parts = line.split("\t")
            parts = [p.strip('"') for p in parts if p]
            if len(parts) == 2:
                key, value = parts[0], parts[1]
            elif len(parts) == 1:
                key, value = parts[0], None
            else:
                key, value = None, None
            if value is not None:
                stack[-1][key] = value
            else:
                current_key = key
    acf = stack[0]
    data = {}
    for mod_id, mod_info in acf["AppWorkshop"]["WorkshopItemsInstalled"].items():
        data[mod_id] = str(mod_info["timeupdated"])
    return data


async def search_mods(
    search_text: str,
    appid: int,
    page: int = 1,
    numperpage: int = 10,
    language: int = 6,
) -> List[dict]:
    """关键词搜索模组.

    Args:
        search_text (str): 关键词.
        appid (int): appid.
        page (页): 关键词.
        numperpage (int): 每页数量.
        language (int): 语言.

    Returns:
        List[dict]: 模组.
    """
    async with httpx.AsyncClient(timeout=10) as client:
        url = "http://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
        params = {
            "appid": appid,
            "page": page,
            "numperpage": numperpage,
            "language": language,
            "search_text": search_text,
            "return_tags": True,
            "key": STEAM_API_KEY,
        }
        response = await client.get(url, params=params)
    return response.json()
