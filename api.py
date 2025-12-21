import os
import json
import subprocess
import urllib.request
from fastapi import FastAPI, Query
from pydantic import BaseModel
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path(__file__).parent / "config.json"

DEFAULTS = {
    "MC_DIR": str(Path.home() / "mc" / "server"),
    "START_CMD": "java -Xms2G -Xmx5G -jar paper.jar nogui",
    "SESSION": "mc",
    "LOG_FILE": str(Path("/tmp/mc_console.log")),
    "PLUGINS_DIR": None  # if None -> MC_DIR/plugins
}

def load_config():
    cfg = DEFAULTS.copy()
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text())
            cfg.update({k: v for k, v in data.items() if v is not None})
        except Exception:
            pass
    # environment overrides
    for k in ("MC_DIR", "START_CMD", "SESSION", "LOG_FILE", "PLUGINS_DIR"):
        if os.environ.get(k):
            cfg[k] = os.environ[k]
    if not cfg["PLUGINS_DIR"]:
        cfg["PLUGINS_DIR"] = str(Path(cfg["MC_DIR"]) / "plugins")
    return cfg

cfg = load_config()
MC_DIR = cfg["MC_DIR"]
START_CMD = cfg["START_CMD"]
SESSION = cfg["SESSION"]
LOG_FILE = cfg["LOG_FILE"]
PLUGINS_DIR = cfg["PLUGINS_DIR"]

app = FastAPI()

class Cmd(BaseModel):
    cmd: str

class Plugin(BaseModel):
    url: str
    filename: Optional[str] = None

def run(cmd: str):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

@app.post("/start")
def start():
    if run(f"tmux has-session -t {SESSION}").returncode == 0:
        return {"status": "already running"}
    # start inside tmux; use bash -lc to allow complex start commands
    safe_cmd = f"tmux new -d -s {SESSION} bash -lc 'cd \"{MC_DIR}\" && {START_CMD} | tee \"{LOG_FILE}\"'"
    r = run(safe_cmd)
    return {"status": "started", "rc": r.returncode, "stderr": r.stderr}

@app.post("/stop")
def stop():
    # send stop; allow it a moment
    run(f"tmux send-keys -t {SESSION} stop Enter")
    return {"status": "stopping"}

@app.post("/cmd")
def command(c: Cmd):
    run(f"tmux send-keys -t {SESSION} '{c.cmd}' Enter")
    return {"sent": c.cmd}

@app.get("/console")
def console(lines: int = Query(200, ge=1, le=20000)):
    p = Path(LOG_FILE)
    if not p.exists():
        return {"log": ""}
    with p.open("rb") as f:
        # tail last N lines efficiently
        try:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = 1024
            data = b""
            while lines > 0 and size > 0:
                read_size = min(block, size)
                f.seek(size - read_size)
                chunk = f.read(read_size)
                data = chunk + data
                size -= read_size
                # crude count
                if data.count(b"\n") > lines + 5:
                    break
            text = data.decode(errors="replace")
            text_lines = text.splitlines()[-lines:]
            return {"log": "\n".join(text_lines)}
        except Exception:
            return {"log": p.read_text(errors="replace")[-10000:]}

@app.get("/status")
def status():
    running = run(f"tmux has-session -t {SESSION}").returncode == 0
    return {"running": running, "mc_dir": MC_DIR, "start_cmd": START_CMD}

@app.post("/plugin")
def plugin(p: Plugin):
    Path(PLUGINS_DIR).mkdir(parents=True, exist_ok=True)
    filename = p.filename if p.filename else p.url.split("/")[-1].split("?")[0] or "plugin.jar"
    dest = str(Path(PLUGINS_DIR) / filename)
    try:
        urllib.request.urlretrieve(p.url, dest)
    except Exception as e:
        return {"error": str(e)}
    return {"installed": filename, "path": dest}
