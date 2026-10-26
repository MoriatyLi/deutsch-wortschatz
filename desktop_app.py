"""Windows desktop launcher for Deutsch Wortschatz."""
from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "app_resources"
    return Path(__file__).resolve().parent


def data_root(override: str | None = None) -> Path:
    if override:
        return Path(override).expanduser().resolve()
    local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return local / "DeutschWortschatz"


def initialize_data(target: Path, resources: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    db = target / "vocab.db"
    seed = resources / "user_data" / "vocab.db"
    if not db.exists() and seed.exists():
        with tempfile.NamedTemporaryFile(dir=target, suffix=".seed", delete=False) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copy2(seed, temporary)
            try:
                os.link(temporary, db)
            except FileExistsError:
                pass
        finally:
            temporary.unlink(missing_ok=True)
    audio = target / "audio"
    audio.mkdir(exist_ok=True)
    seed_audio = resources / "user_data" / "audio"
    if seed_audio.exists():
        for source in seed_audio.iterdir():
            destination = audio / source.name
            if source.is_file() and not destination.exists():
                shutil.copy2(source, destination)

    from vocab import Store

    store = Store(db)
    bundled_dictionary = resources / "dictionary" / "de-zh.db"
    if not bundled_dictionary.is_file():
        bundled_dictionary = resources / "data" / "dictionaries" / "de-zh.db"
    if not bundled_dictionary.is_file():
        raise FileNotFoundError("离线词典文件缺失，请保留完整应用文件夹。")
    if store.get_setting("bundled_dictionary_path") != str(bundled_dictionary):
        old_default = store.get_setting("bundled_dictionary_path")
        current = store.get_setting("offline_path")
        if not current or current == old_default:
            store.set_setting("offline_path", bundled_dictionary)
        store.set_setting("bundled_dictionary_path", bundled_dictionary)
    if store.get_setting("online") == "":
        store.set_setting("online", "0")
    if store.get_setting("tts") == "":
        store.set_setting("tts", "0")


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def watch_parent(pid: int) -> None:
    """Stop the local service even if Windows forcibly closes its app window."""
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if not handle:
        os._exit(0)

    def wait():
        result = kernel.WaitForSingleObject(handle, 0xFFFFFFFF)
        kernel.CloseHandle(handle)
        if result == 0:
            os._exit(0)

    threading.Thread(target=wait, daemon=True).start()


def serve(data: Path, port: int) -> int:
    resources = resource_root()
    os.chdir(resources)
    sys.path.insert(0, str(resources))
    os.environ["DEUTSCH_VOCAB_DATA_DIR"] = str(data)
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    from streamlit.web.cli import main

    sys.argv = ["streamlit", "run", str(resources / "app.py"),
                "--global.developmentMode", "false", "--server.fileWatcherType", "none",
                "--server.address", "127.0.0.1", "--server.port", str(port),
                "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    main()
    return 0


def launch(data: Path, no_window: bool = False) -> int:
    resources = resource_root()
    initialize_data(data, resources)
    port = available_port()
    url = f"http://127.0.0.1:{port}"
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command.append(str(Path(__file__).resolve()))
    command += ["--serve", "--data-dir", str(data), "--port", str(port),
                "--parent-pid", str(os.getpid())]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    log_path = data / "desktop.log"
    log = log_path.open("a", encoding="utf-8")
    child = subprocess.Popen(command, cwd=resources, stdin=subprocess.DEVNULL,
                             stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    try:
        deadline = time.monotonic() + 60
        ready = False
        while time.monotonic() < deadline and child.poll() is None:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                    ready = True
                    break
            except OSError:
                time.sleep(0.25)
        if not ready:
            raise RuntimeError(f"本地服务未能启动。请查看日志：{log_path}")
        if no_window:
            (data / "server-url.txt").write_text(url, encoding="utf-8")
            while child.poll() is None:
                time.sleep(1)
            return 0

        import webview

        webview.create_window("Deutsch Wortschatz · 德语词库", url,
                              width=1280, height=850, min_size=(820, 620))
        webview.start(gui="edgechromium", storage_path=str(data / "webview"))
        return 0
    except Exception:
        log.write(traceback.format_exc())
        log.flush()
        raise
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
        log.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--check-runtime", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--data-dir")
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--no-window", action="store_true", help="start the local server without opening a window")
    args = parser.parse_args()
    data = data_root(args.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    log_path = data / ("server.log" if args.serve else "launcher.log")
    with log_path.open("a", encoding="utf-8", buffering=1) as log:
        with redirect_stdout(log), redirect_stderr(log):
            try:
                if args.check_runtime:
                    from webview.platforms import winforms
                    if winforms.renderer != "edgechromium":
                        raise RuntimeError("需要安装 Microsoft Edge WebView2 Runtime。")
                    report = {"desktop_renderer": winforms.renderer,
                              "frozen": bool(getattr(sys, "frozen", False))}
                    (data / "runtime-check.json").write_text(
                        json.dumps(report, ensure_ascii=False), encoding="utf-8")
                    return 0
                if args.serve:
                    if args.parent_pid:
                        watch_parent(args.parent_pid)
                    initialize_data(data, resource_root())
                    return serve(data, args.port)
                return launch(data, args.no_window)
            except Exception:
                traceback.print_exc()
                if not (args.serve or args.no_window or args.check_runtime) and sys.platform == "win32":
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(None,
                        f"应用未能启动，请保留完整应用文件夹。\n日志：{log_path}",
                        "Deutsch Wortschatz", 0x10)
                return 1


if __name__ == "__main__":
    raise SystemExit(main())
