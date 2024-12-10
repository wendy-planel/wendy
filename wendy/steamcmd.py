from typing import List, Dict

import os

import httpx

from wendy.settings import STEAM_API_KEY


async def dst_version() -> str:
    """获取dst版本号.

    Returns:
        str: dst版本号
    """
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.steamcmd.net/v1/info/343050")
    return response.json()["data"]["343050"]["depots"]["branches"]["public"]["buildid"]


async def mods_last_updated(mods: List[str]) -> Dict[str, str]:
    """接口获取模组最后一次更新时间.

    Args:
        mods (List[str]): 模组列表.

    Returns:
        Dict[str, str]: {"模组ID": "最后一次更新时间"}.
    """
    data = {}
    response = await publishedfiledetails(mods)
    for mod_info in response["response"]["publishedfiledetails"]:
        data[mod_info["publishedfileid"]] = str(mod_info["time_updated"])
    return data


def parse_mods_last_updated(acf_file_path: str) -> Dict[str, str]:
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


async def publishedfiledetails(mods: List[str]) -> dict:
    url = "http://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
    post_data = {
        "itemcount": len(mods),
    }
    for i in range(len(mods)):
        post_data[f"publishedfileids[{i}]"] = mods[i]
    async with httpx.AsyncClient() as client:
        response = await client.post(url, data=post_data)
    return response.json()


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
    async with httpx.AsyncClient() as client:
        url = "https://api.steampowered.com/IPublishedFileService/QueryFiles/v1/"
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
