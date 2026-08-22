#!/usr/bin/env python3
"""Small single-purpose YouTube downloader web service."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import subprocess
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse


ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8080"))
MAX_BODY = 16 * 1024
TIMEOUT = int(os.environ.get("YTDLP_TIMEOUT_SECONDS", "1800"))
FORMATS = {
    "best": ("bv*+ba/b", "video/mp4", ".mp4"),
    "mp4-1080p": ("bv*[height<=1080][ext=mp4]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]", "video/mp4", ".mp4"),
    "mp4-720p": ("bv*[height<=720][ext=mp4]+ba[ext=m4a]/bv*[height<=720]+ba/b[height<=720]", "video/mp4", ".mp4"),
    "webm": ("bv*[ext=webm]+ba[ext=webm]/b[ext=webm]", "video/webm", ".webm"),
    "mp3": ("bestaudio/best", "audio/mpeg", ".mp3"),
}
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def valid_youtube_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname in ALLOWED_HOSTS and bool(parsed.path)


def downloader_command(url: str, choice: str, output: Path) -> list[str]:
    fmt, _, _ = FORMATS[choice]
    executable = shutil.which(os.environ.get("YTDLP_BIN", "yt-dlp"))
    base = [executable] if executable else [os.environ.get("PYTHON", "python3"), "-m", "yt_dlp"]
    command = base + ["--no-playlist", "--newline", "--no-warnings", "--format", fmt, "--output", str(output), url]
    if choice.startswith("mp4") or choice == "best":
        command[command.index("--output"):command.index("--output")] = ["--merge-output-format", "mp4"]
    if choice == "mp3":
        command[command.index("--output"):command.index("--output")] = ["--extract-audio", "--audio-format", "mp3", "--audio-quality", "192K"]
    return command


def find_result(folder: Path, choice: str) -> Path | None:
    expected = FORMATS[choice][2]
    candidates = [item for item in folder.iterdir() if item.is_file() and not item.name.endswith((".part", ".ytdl"))]
    preferred = [item for item in candidates if item.suffix.lower() == expected]
    return max(preferred or candidates, key=lambda item: item.stat().st_mtime, default=None)


class Handler(BaseHTTPRequestHandler):
    server_version = "YouTubeDownloader/1.0"

    def end_json(self, status: int, payload: dict) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/api/health":
            self.end_json(HTTPStatus.OK, {"ok": True})
            return
        if self.path not in ("/", "/index.html"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = (ROOT / "index.html").read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/api/download":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("请求内容过大或为空。")
            payload = json.loads(self.rfile.read(length))
            url = str(payload.get("url", "")).strip()
            choice = str(payload.get("format", "mp4-1080p"))
            if not valid_youtube_url(url):
                raise ValueError("请输入有效的 HTTPS YouTube 视频地址。")
            if choice not in FORMATS:
                raise ValueError("不支持的下载格式。")
            self.download_and_send(url, choice)
        except ValueError as error:
            self.end_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except subprocess.TimeoutExpired:
            self.end_json(HTTPStatus.GATEWAY_TIMEOUT, {"error": "下载超时，请尝试更低画质或较短视频。"})
        except Exception as error:  # Keep internal details out of the response.
            print(f"download error: {error}", flush=True)
            self.end_json(HTTPStatus.BAD_GATEWAY, {"error": "下载失败，请检查视频可访问性或服务器依赖。"})

    def download_and_send(self, url: str, choice: str) -> None:
        with tempfile.TemporaryDirectory(prefix="youtube-download-") as temp_dir:
            folder = Path(temp_dir)
            output = folder / "%(title).180s.%(ext)s"
            command = downloader_command(url, choice, output)
            completed = subprocess.run(command, cwd=folder, capture_output=True, text=True, timeout=TIMEOUT)
            if completed.returncode != 0:
                print(completed.stderr[-4000:], flush=True)
                raise RuntimeError("yt-dlp exited with a non-zero status")
            result = find_result(folder, choice)
            if result is None:
                raise RuntimeError("No output file was produced")
            content_type = FORMATS[choice][1]
            filename = result.name
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(result.stat().st_size))
            self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with result.open("rb") as stream:
                shutil.copyfileobj(stream, self.wfile, length=1024 * 1024)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    print(f"Serving {ROOT} on http://0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
