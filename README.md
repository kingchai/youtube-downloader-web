# YouTube 视频下载器

一个无前端依赖、无 Python Web 框架依赖的单页下载器。服务端使用 `yt-dlp` 下载单个 YouTube 视频，支持 MP4 1080p、MP4 720p、最佳可用画质、WebM 和 MP3。

## 本地运行

```bash
python3 -m pip install yt-dlp
# MP3 或合并音视频还需要 ffmpeg
python3 server.py
```

访问 `http://127.0.0.1:8080`。

## Docker 运行

```bash
docker compose up -d --build
```

服务监听 `8080` 端口。生产环境建议在前面配置 HTTPS 反向代理，并通过防火墙限制访问范围；不要把它改造成任意 URL 下载器。

## API

- `GET /api/health`：健康检查
- `POST /api/download`：JSON body `{ "url": "https://www.youtube.com/watch?v=...", "format": "mp4-1080p" }`

播放列表参数默认忽略，只下载单个视频。仅下载你有权保存和使用的内容，并遵守 YouTube 的服务条款和内容权利要求。
