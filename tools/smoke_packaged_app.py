"""Exercise the frozen server over its local protocol, without opening a browser."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import time
from urllib.request import urlopen

from streamlit.proto.BackMsg_pb2 import BackMsg
from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
from websockets.sync.client import connect


def run_script(ws, values=None, checks=()):
    request = BackMsg()
    request.rerun_script.query_string = ""
    for widget_id, value in (values or {}).items():
        widget = request.rerun_script.widget_states.widgets.add(id=widget_id)
        if isinstance(value, bool):
            if widget_id in checks:
                widget.bool_value = value
            else:
                widget.trigger_value = value
        else:
            widget.string_value = value
    ws.send(request.SerializeToString())
    elements = []
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        message = ForwardMsg.FromString(ws.recv(timeout=10))
        if message.WhichOneof("type") == "delta" and message.delta.HasField("new_element"):
            element = message.delta.new_element
            if element.HasField("exception"):
                raise AssertionError(str(element.exception))
            elements.append(element)
        if message.WhichOneof("type") == "script_finished":
            if message.script_finished == ForwardMsg.FINISHED_WITH_COMPILE_ERROR:
                raise AssertionError("Frozen script compile failure")
            if message.script_finished == ForwardMsg.FINISHED_SUCCESSFULLY:
                return elements
    raise TimeoutError("No successful script completion")


def session(url):
    return connect(url.replace("http", "ws", 1) + "/_stcore/stream",
                   origin=url, subprotocols=["streamlit"], max_size=16 * 1024 * 1024)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("exe", type=Path)
    parser.add_argument("data", type=Path)
    args = parser.parse_args()
    exe, data = args.exe.resolve(), args.data.resolve()
    if (data / "vocab.db").exists():
        raise ValueError("Use a fresh isolated smoke-test directory")
    data.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    environment["PATH"] = os.path.join(system_root, "System32")
    runtime = subprocess.run([str(exe), "--check-runtime", "--data-dir", str(data)],
                             cwd=data, env=environment, timeout=30,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if runtime.returncode:
        raise AssertionError((data / "launcher.log").read_text(encoding="utf-8"))
    runtime_report = json.loads((data / "runtime-check.json").read_text(encoding="utf-8"))
    assert runtime_report == {"desktop_renderer": "edgechromium", "frozen": True}

    def start():
        child = subprocess.Popen([str(exe), "--serve", "--data-dir", str(data),
                                  "--port", str(port)], cwd=data, env=environment,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        for _ in range(160):
            try:
                with urlopen(url + "/_stcore/health", timeout=0.5) as response:
                    assert response.read() == b"ok"
                return child
            except OSError:
                if child.poll() is not None:
                    raise AssertionError((data / "server.log").read_text(encoding="utf-8"))
                time.sleep(0.25)
        child.terminate()
        child.wait(timeout=10)
        raise TimeoutError((data / "server.log").read_text(encoding="utf-8"))

    child = start()
    report = {"exe": str(exe), "health": "ok", "external_python_on_path": False,
              "desktop_runtime": runtime_report}
    try:
        with urlopen(url, timeout=5) as response:
            html = response.read().decode()
        asset = re.search(r'src="(\./static/[^\"]+\.js)"', html)
        assert asset, "Frontend bundle reference missing"
        with urlopen(url + "/" + asset.group(1).removeprefix("./"), timeout=5) as response:
            assert len(response.read()) > 1000
        report["frontend_assets"] = "ok"
        with session(url) as ws:
            elements = run_script(ws)
            assert "运行模式：完全离线" in str(elements)
            vault = data / 'test-vault'
            (vault / '.obsidian').mkdir(parents=True)
            destination = vault / '德语单词.md'
            path_id = next(element.text_input.id for element in elements
                           if element.HasField('text_input') and element.text_input.label == '单词表保存位置（Markdown 文件）')
            auto_id = next(element.checkbox.id for element in elements
                           if element.HasField('checkbox') and element.checkbox.label == '保存词条后自动更新单词表')
            save_id = next(element.button.id for element in elements
                           if element.HasField('button') and element.button.label == '确定位置并保存单词表')
            elements = run_script(ws, {path_id: str(destination), auto_id: True, save_id: True}, checks={auto_id})
            assert destination.is_file()
            destination.write_bytes(destination.read_bytes() + '\n个人笔记保留\n'.encode())
            widgets = {element.text_input.label: element.text_input.id
                       for element in elements if element.HasField("text_input")}
            button = next(element.button.id for element in elements
                          if element.HasField("button") and element.button.label == "加入词库")
            run_script(ws, {widgets["德语单词或短语"]: "Hund", button: True})
            text = destination.read_text('utf-8')
            assert 'Hund' in text and '狗' in text and text.endswith('个人笔记保留\n')
        with sqlite3.connect(data / "vocab.db") as conn:
            row = conn.execute("SELECT chinese_meaning,article FROM words WHERE word='Hund'").fetchone()
            assert row and "狗" in row[0] and row[1] == "der", row
            settings = dict(conn.execute("SELECT key,value FROM settings"))
            bundled = exe.parent / "_internal" / "app_resources" / "dictionary" / "de-zh.db"
            assert Path(settings["offline_path"]) == bundled, settings["offline_path"]
            assert settings["online"] == "0" and settings["tts"] == "0"
            wasser = conn.execute("SELECT chinese_meaning,audio_file FROM words WHERE word_key='wasser'").fetchone()
            if wasser:
                assert "水" in wasser[0]
                if wasser[1]:
                    assert (data / "audio" / wasser[1]).is_file()
        report.update(offline_add_Hund=list(row), seed_Wasser="retained" if wasser else "not included in clean seed",
                      dictionary_path="bundled", initial_script="no exceptions",
                      word_table='chosen path and auto-update, personal notes preserved')
        child.terminate()
        child.wait(timeout=10)
        child = start()
        with session(url) as ws:
            run_script(ws)
        with sqlite3.connect(data / "vocab.db") as conn:
            assert conn.execute("SELECT count(*) FROM words WHERE word='Hund'").fetchone()[0] == 1
        report["restart_persistence"] = "ok"
    finally:
        child.terminate()
        child.wait(timeout=10)

    # Exercise the actual parent launcher and its abrupt-exit cleanup, with no GUI.
    parent = subprocess.Popen([str(exe), "--no-window", "--data-dir", str(data)],
                              cwd=data, env=environment,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        url_file = data / "server-url.txt"
        for _ in range(160):
            if url_file.exists():
                break
            if parent.poll() is not None:
                raise AssertionError((data / "launcher.log").read_text(encoding="utf-8"))
            time.sleep(0.25)
        assert url_file.exists(), "Parent launcher not ready"
        child_url = url_file.read_text(encoding="utf-8")
        with urlopen(child_url + "/_stcore/health", timeout=5) as response:
            assert response.read() == b"ok"
        parent.terminate()
        parent.wait(timeout=10)
        for _ in range(40):
            try:
                urlopen(child_url + "/_stcore/health", timeout=0.2).close()
                time.sleep(0.1)
            except OSError:
                report["parent_exit_stops_service"] = "ok"
                break
        assert report.get("parent_exit_stops_service") == "ok", "Orphan service remains"
    finally:
        if parent.poll() is None:
            parent.terminate()
            parent.wait(timeout=10)
    (data / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
