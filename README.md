<div align="center">
  <img src="https://raw.githubusercontent.com/ylei2024/wendy/main/docs/wendy.png" style="width:150px; height:200px; border-radius:50%;"/>
</div>

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/ylei2024/wendy/main.yml)

# wendy-plane

## 预览
  <div>
    <img src="https://raw.githubusercontent.com/ylei2024/wendy/main/docs/plane.png" style="width:800px; height:400px;"/>
  </div>

## 功能
- 容器化快速开服(支持远程docker api)
- 上传存档文件开服
- 添加配置模组(需要配置 STEAM_API_KEY 且确保部署物理机能访问 steam)
- 监听更新模组、游戏版本
- 存档文件下载
- 远程执行控制台指令
- 实时日志

## 部署

- docker 安装

  https://docs.docker.com/engine/install/

- 下载 docker-compose.yml

  ```bash
  wget https://raw.githubusercontent.com/ylei2024/wendy/main/docker-compose.yml
  ```

- 启动
  ```bash
  docker compose up -d
  ```
  或者
  ```bash
  export STEAM_API_KEY=xxxx && docker compose up -d
  ```
- 说明

  - 存档数据将会挂在到当前目录${PWD}/data
  - 如果配置了 STEAM_API_KEY 且物理机网络能访问 steam，面板将支持搜索添加模组

- 面板地址

  http://127.0.0.1:8000

- 后端接口文档

  http://127.0.0.1:8001/docs

## 相关项目地址

- wendy-plane 前端

  https://github.com/wendy-plane/wendy-plane

- wendy-plane 后端

  https://github.com/wendy-plane/wendy

- 饥荒镜像构建

  https://github.com/ylei2024/dontstarve-server-docker

- 饥荒群机器人

  https://github.com/wendy-plane/dst-bot

## TODO

- 大厅查询
