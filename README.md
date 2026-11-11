# 开源集 OpenShelf

个人开源软件目录，支持从 GitHub 仓库提取信息、分类整理、发布展示与 AI 辅助简介。

## Docker Compose 部署

新建 `compose.yaml`：

```yaml
services:
  openshelf:
    image: ghcr.io/ncare/openshelf:latest
    ports:
      - "8000:8000"
    volumes:
      - ./data:/data
    restart: unless-stopped
```

执行 `docker compose up -d`，然后访问 `http://localhost:8000`。镜像由 GitHub Actions 构建，支持 `linux/amd64` 和 `linux/arm64`；首次发布后可能需要在 GitHub Packages 中将镜像设为公开才能匿名拉取。

`./data` 存放数据库、设置、图标和截图，更新容器时请保留该目录。可在设置页面导出和恢复软件、分类及图片；备份不包含密钥和 AI 使用记录。迁移完整数据时，停止服务后备份整个 `data` 目录。

**访问限制：**目前没有后台登录或权限控制，任何能够访问服务的人都可以修改数据并查看已保存的 AI API Key。请仅在可信网络使用，不要直接暴露到公网。数据库和完整数据目录备份中含有密钥，请限制访问。

## 从源码构建

```bash
git clone https://github.com/Ncare/OpenShelf.git
cd OpenShelf
docker compose up -d --build
```

仓库中的 Compose 文件使用本地源码构建；上面的示例使用已发布镜像。

## 本地开发

需要 Python 3.12+ 和 Node.js 22+：

```bash
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload
```

另开终端：

```bash
cd frontend
npm ci
npm run dev
```

前端开发服务器将 `/api` 和 `/images` 代理到 8000 端口，`npm run build` 生成的静态文件由后端提供。

## 使用说明

在后台粘贴 GitHub 仓库链接，检查自动提取的信息并保存，再手动发布。AI 默认关闭，可配置 OpenAI 兼容接口；启用后仓库描述和 README 会发送到所配置的服务。GitHub Token 可选。

支持从部分图片来源下载候选图片，也可上传 PNG、JPEG、GIF、WebP 或符合安全限制的 SVG。刷新仓库信息不会覆盖手动编辑的简介、分类和平台。

前台搜索会在软件名称、简介、分类、平台、标签和仓库地址中匹配多个关键词，并提供即时联想、相关度/Star/更新时间排序、关键词高亮及可分享的筛选 URL。按 `Ctrl/Cmd + K` 或 `/` 可快速聚焦搜索框。
