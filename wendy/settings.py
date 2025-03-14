import os


APP_NAME = "wendy"
DEBUG = os.environ.get("DEBUG")
GAME_ARCHIVE_PATH = os.environ.get("GAME_ARCHIVE_PATH")
DOCKER_API_DEFAULT = os.environ.get(
    "DOCKER_API_DEFAULT",
    default="unix:///var/run/docker.sock",
)
DST_IMAGE = os.environ.get("DST_IMAGE", default="ylei2023/dontstarvetogether")

# 数据量配置
DATABASE_URL = os.environ.get("DATABASE_URL", default="sqlite://wendy.sqlite3")
TORTOISE_ORM = {
    "connections": {"default": DATABASE_URL},
    "apps": {
        APP_NAME: {
            "models": ["wendy.models", "aerich.models"],
            "default_connection": "default",
        },
    },
    "timezone": "Asia/Shanghai",
}
# STEAM_API_KEY
STEAM_API_KEY = os.environ.get("STEAM_API_KEY")
