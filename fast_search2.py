#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Fast File & Content Search Tool (Windows + Linux/macOS)
- Everything (Win) / fd (Unix) → filename
- ripgrep → content
- Icons, exclude, apps, copy, folder
- o/f/c = act & STAY | q = SKIP TO NEXT
"""

import os
import sys
import shutil
import subprocess
import argparse
import string
import time
import json
import platform
from pathlib import Path
from typing import List, Optional, Tuple, Set
from dataclasses import dataclass

# ================================
# CONFIG
# ================================
VERSION = "1.1.0"
DEFAULT_MAX_RESULTS = 1000
CONFIG_PATH = Path.home() / ".fastsearch.json"
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

COMMON_FOLDERS = [
    "Desktop",
    "Documents",
    "Downloads",
    "Pictures",
    "Videos",
    "Music",
    "OneDrive",
    "Google Drive",
    "Dropbox",
]


# ================================
# DATACLASS
# ================================
@dataclass
class Tools:
    filename_tool: str  # es.exe or fd
    content_tool: str  # rg


# ================================
# CONFIG
# ================================
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[Warning] Config load failed: {e}", file=sys.stderr)
        return {}


def save_config(config: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        print(f"[Warning] Config save failed: {e}", file=sys.stderr)


# ================================
# TOOLS: AUTO-INSTALL
# ================================
def install_winget_tool(id: str, exe: str) -> str:
    print(f"   [Installing] {exe} via winget...")
    subprocess.run(
        [
            "winget",
            "install",
            "--id",
            id,
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
        check=True,
        timeout=300,
    )
    path = shutil.which(exe)
    if not path:
        sys.exit(f"[Error] {exe} not found after install.")
    return path


def install_brew_tool(name: str) -> str:
    print(f"   [Installing] {name} via brew...")
    subprocess.run(["brew", "install", name], check=True)
    return shutil.which(name)


def install_apt_tool(name: str) -> str:
    print(f"   [Installing] {name} via apt...")
    subprocess.run(["sudo", "apt", "update", "-qq"], check=True)
    subprocess.run(["sudo", "apt", "install", "-y", name], check=True)
    return shutil.which(name)


def ensure_tools() -> Tools:
    es_path = rg_path = fd_path = None

    if IS_WINDOWS:
        if not shutil.which("winget"):
            sys.exit("[Error] winget not found. Install from Microsoft Store.")

        # Everything
        es_path = shutil.which("es.exe")
        if not es_path:
            candidates = [
                Path(r"C:\Program Files\Everything\es.exe"),
                Path(r"C:\Program Files (x86)\Everything\es.exe"),
                Path(os.getenv("LOCALAPPDATA", ""))
                / "Programs"
                / "Everything"
                / "es.exe",
            ]
            for p in candidates:
                if p.exists():
                    es_path = str(p)
                    break
        if not es_path:
            es_path = install_winget_tool("voidtools.Everything", "es.exe")

        # Start service
        try:
            result = subprocess.run(
                ["sc", "query", "Everything"], capture_output=True, text=True
            )
            if "RUNNING" not in result.stdout:
                subprocess.run(["net", "start", "Everything"], check=False)
                time.sleep(3)
        except:
            pass

        # ripgrep
        rg_path = shutil.which("rg") or install_winget_tool(
            "BurntSushi.ripgrep.MSVC", "rg"
        )

    else:  # Linux/macOS
        rg_path = shutil.which("rg") or (
            install_brew_tool("ripgrep") if IS_MACOS else install_apt_tool("ripgrep")
        )
        fd_path = shutil.which("fd") or (
            install_brew_tool("fd") if IS_MACOS else install_apt_tool("fd-find")
        )

    filename_tool = es_path or fd_path
    content_tool = rg_path

    if not filename_tool or not content_tool:
        sys.exit("[Error] Failed to install required tools.")

    print(f"   [OK] Filename: {Path(filename_tool).name}")
    print(f"   [OK] Content: rg")

    # Indexing status
    if IS_WINDOWS and es_path:
        try:
            status = subprocess.check_output(
                [es_path, "-get-index-status"], text=True, timeout=5
            ).strip()
            print(f"   [Info] Everything index: {status}")
        except:
            print(f"   [Info] Everything index: unknown")

    return Tools(filename_tool, content_tool)


# ================================
# UTILS
# ================================
def clear_screen():
    os.system("cls" if IS_WINDOWS else "clear")


def run_cmd(cmd, timeout=60) -> List[str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return [
            line.strip() for line in result.stdout.strip().splitlines() if line.strip()
        ]
    except Exception as e:
        print(f"[Warning] Cmd failed: {e}", file=sys.stderr)
        return []


def get_drives() -> List[str]:
    if IS_WINDOWS:
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    else:
        return ["/"]


def icon_for(path: str) -> str:
    ext = Path(path).suffix.lower()
    icons = {
        ".pdf": "PDF",
        ".docx": "Word",
        ".xlsx": "Excel",
        ".py": "Python",
        ".js": "JS",
        ".jpg": "Image",
        ".png": "Image",
        ".mp4": "Video",
        ".mp3": "Music",
        ".zip": "Archive",
        ".txt": "Text",
        ".log": "Log",
        ".json": "JSON",
        ".xml": "XML",
    }
    return f"{path} [{icons.get(ext, 'File')}]"


# ================================
# EXCLUDE & PATTERN
# ================================
def should_exclude(path: str, exclude: List[str]) -> bool:
    p = Path(path)
    for pattern in exclude:
        if p.match(pattern) or pattern in p.parts:
            return True
    return False


def build_everything_pattern(user_input: str) -> str:
    s = user_input.strip()
    if not s:
        return "*"
    if "." in s and "/" not in s and "*" not in s and "?" not in s:
        return s
    if "*" in s or "?" in s or s.startswith("re:"):
        return s
    if "/" in s:
        name, ext = s.split("/", 1)
        ext = ext.lstrip(".")
        return f"*{name}*.{ext}" if ext else f"*{name}*"
    return f"*{s}*"


# ================================
# FILENAME SEARCH
# ================================
def smart_search_filename(query: str, tools: Tools, config: dict) -> List[str]:
    max_res = config.get("max_results", DEFAULT_MAX_RESULTS)
    exclude = config.get("exclude", [])
    extra_folders = config.get("extra_folders", [])
    results: List[str] = []
    scanned: Set[str] = set()

    pattern = build_everything_pattern(query)
    print(f"   Pattern → {pattern}")

    def search_path(root: Path):
        if str(root) in scanned or not root.exists():
            return
        scanned.add(str(root))
        print(f"   → {root}")

        if IS_WINDOWS:
            cmd = [tools.filename_tool, "-path", str(root), "-n", str(max_res), pattern]
        else:
            cmd = [
                tools.filename_tool,
                pattern,
                "--path",
                str(root),
                "--max-results",
                str(max_res),
            ]
        hits = run_cmd(cmd, 60)
        hits = [h for h in hits if not should_exclude(h, exclude)]
        results.extend(hits)
        print(f"     Found {len(hits)}")

    # Common folders
    for drive in get_drives():
        user_root = (
            Path(drive) / "Users" / os.getenv("USERNAME" if IS_WINDOWS else "USER", "")
        )
        for folder in COMMON_FOLDERS:
            p = user_root / folder
            if p.exists():
                search_path(p)
        for extra in extra_folders:
            p = Path(extra)
            if p.is_absolute() and p.exists():
                search_path(p)

    results = list(dict.fromkeys(results))[:max_res]
    print(f"\n   Found {len(results)} in common locations.")

    if len(results) >= max_res:
        return results

    choice = (
        input(f"   Scan full drive(s) {'/'.join(get_drives())}? [n]: ").strip().lower()
    )
    if choice not in ("y", "yes", "all"):
        return results

    for drive in get_drives():
        if IS_WINDOWS:
            cmd = [tools.filename_tool, "-path", drive, "-n", str(max_res), pattern]
        else:
            cmd = [tools.filename_tool, pattern, "--max-results", str(max_res)]
        hits = run_cmd(cmd, 180)
        hits = [h for h in hits if h not in results and not should_exclude(h, exclude)]
        results.extend(hits)
        if len(results) >= max_res:
            break

    return list(dict.fromkeys(results))[:max_res]


# ================================
# CONTENT SEARCH
# ================================
def smart_search_content(
    text: str, ext: Optional[str], tools: Tools, config: dict
) -> List[str]:
    max_res = config.get("max_results", DEFAULT_MAX_RESULTS)
    exclude = config.get("exclude", [])
    extra_folders = config.get("extra_folders", [])
    results = []
    scanned = set()

    glob = f"*.{ext}" if ext and ext.strip() else None

    def build_rg_cmd(root: str):
        cmd = [
            tools.content_tool,
            "--files-with-matches",
            "--no-messages",
            "--ignore-case",
            "--follow",
            text,
            root,
        ]
        if glob:
            cmd.extend(["--glob", glob])
        for ex in exclude:
            cmd.extend(["--glob", f"!{ex}"])
        return cmd

    def search_path(root: Path):
        if str(root) in scanned or not root.exists():
            return
        scanned.add(str(root))
        print(f"   → {root}")
        hits = run_cmd(build_rg_cmd(str(root)), 180)
        results.extend(hits)
        print(f"     Found {len(hits)}")

    for drive in get_drives():
        user_root = (
            Path(drive) / "Users" / os.getenv("USERNAME" if IS_WINDOWS else "USER", "")
        )
        for folder in COMMON_FOLDERS:
            path = user_root / folder
            if path.exists():
                search_path(path)
        for extra in extra_folders:
            p = Path(extra)
            if p.is_absolute() and p.exists():
                search_path(p)

    results = [r for r in results if not should_exclude(r, exclude)]
    results = list(dict.fromkeys(results))[:max_res]
    print(f"\n   Found {len(results)} in common locations.")

    if len(results) >= max_res:
        return results

    choice = input(f"   Scan full drive(s)? [n]: ").strip().lower()
    if choice not in ("y", "yes"):
        return results

    for drive in get_drives():
        hits = run_cmd(build_rg_cmd(drive), 600)
        hits = [h for h in hits if h not in results and not should_exclude(h, exclude)]
        results.extend(hits)
        if len(results) >= max_res:
            break

    return list(dict.fromkeys(results))[:max_res]


# ================================
# RESULT DISPLAY
# ================================
def display_results(results: List[str]) -> List[str]:
    if not results:
        print("\nNo results.")
        return []

    print(f"\n{len(results)} match(es):")
    to_show = results[:50]
    for i, path in enumerate(to_show, 1):
        print(f"  {i:2}) {icon_for(path)}")  # <-- only ONE call

    if len(results) > 50:
        print(f"  ... and {len(results) - 50} more.")

    raw = input("\nEnter numbers (1,3-5,7) or [Enter]: ").strip()
    if not raw:
        return []

    selected = set()
    for part in raw.replace(" ", "").split(","):
        if "-" in part:
            s, e = part.split("-")
            try:
                s, e = int(s), int(e)
                selected.update(range(s, e + 1))
            except:
                pass
        else:
            try:
                selected.add(int(part))
            except:
                pass

    paths = [results[i - 1] for i in selected if 1 <= i <= len(results)]
    for p in paths:
        print(f"   Queued: {icon_for(p)}")  # <-- only ONE call

    return paths


# ================================
# ACTION MENU – o/f/c = STAY | q = NEXT
# ================================
def post_action_menu(paths: List[str], config: dict):
    if not paths:
        return

    apps = config.get("apps", {})
    for path in paths:
        ext = Path(path).suffix.lower()
        app = apps.get(ext)

        while True:
            print(f"\n{icon_for(path)}")  # <-- only ONE call
            choice = input(" [o]pen [f]older [c]opy [q]uit: ").strip().lower()

            if choice == "q":
                print("   Skipped.")
                break

            if choice in ("o", ""):
                if app:
                    subprocess.Popen([app, path])
                elif IS_WINDOWS:
                    os.startfile(path)
                else:
                    subprocess.run(["open" if IS_MACOS else "xdg-open", path])
                print("   Opened.")

            elif choice == "f":
                folder = str(Path(path).parent)
                if IS_WINDOWS:
                    os.startfile(folder)
                else:
                    subprocess.run(["open" if IS_MACOS else "xdg-open", folder])
                print("   Folder opened.")

            elif choice == "c":
                try:
                    import pyperclip

                    pyperclip.copy(path)
                    print("   Path copied!")
                except ImportError:
                    print(f"   Path: {path}")

            else:
                print("   Unknown command. Try o/f/c/q.")


# ================================
# MAIN MENU
# ================================
def interactive_menu(tools: Tools, config: dict) -> Tuple[str, str, Optional[str]]:
    clear_screen()
    print("=" * 60)
    print("     FAST FILE & CONTENT SEARCH")
    print(f"               v{VERSION}")
    print("=" * 60)
    print("  1) Filename search")
    print("  2) Text inside files")

    choice = input("\nPick [1-2]: ").strip() or "1"
    if choice == "2":
        text = input("\nText to find: ").strip()
        ext = input("File type [all]: ").strip() or None
        return "content", text, ext
    else:
        query = input("\nFilename pattern: ").strip()
        return "filename", query, None


# ================================
# MAIN
# ================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--content", action="store_true")
    parser.add_argument("--ext", help="File extension")
    parser.add_argument("--no-clear", action="store_true")
    args = parser.parse_args()

    config = load_config()
    tools = ensure_tools()
    clear_enabled = not args.no_clear

    if not args.query and not args.content:
        mode, query, ext = interactive_menu(tools, config)
    else:
        mode = "content" if args.content else "filename"
        query = args.query
        ext = args.ext

    if not query:
        print("[Error] Query required.")
        sys.exit(1)

    if clear_enabled:
        clear_screen()

    print(f"\nSearching: {query}")
    results = []
    if mode == "filename":
        results = smart_search_filename(query, tools, config)
    else:
        results = smart_search_content(query, ext, tools, config)

    selected = display_results(results)
    post_action_menu(selected, config)

    input("\nPress Enter to search again...")
    main()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen()
        sys.exit(0)
