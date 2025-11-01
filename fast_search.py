#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Fast File & Content Search Tool (Windows + Linux/macOS) - Enhanced
- Everything (Win) / fd (Unix) → filename
- ripgrep → content
- Icons, exclude, apps, copy, folder, history, filters
- Enhanced UX with fuzzy matching and progress indicators
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
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Set, Dict, Any
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread, Event
import re

# ================================
# CONFIG
# ================================
VERSION = "2.0.0"
DEFAULT_MAX_RESULTS = 1000
CONFIG_PATH = Path.home() / ".fastsearch.json"
LOG_PATH = Path.home() / ".fastsearch.log"
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

# Size constants (bytes)
SIZE_UNITS = {
    "kb": 1024,
    "mb": 1024 * 1024,
    "gb": 1024 * 1024 * 1024,
}

# Setup logging
logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


# ================================
# DATACLASSES
# ================================
@dataclass
class Tools:
    filename_tool: str
    content_tool: str


@dataclass
class SearchHistory:
    mode: str
    query: str
    ext: Optional[str]
    timestamp: float
    results_count: int


@dataclass
class SearchFilters:
    min_size: Optional[int] = None
    max_size: Optional[int] = None
    modified_after: Optional[datetime] = None
    modified_before: Optional[datetime] = None
    created_after: Optional[datetime] = None
    created_before: Optional[datetime] = None


# ================================
# SPINNER
# ================================
class Spinner:
    def __init__(self, message="Searching"):
        self.message = message
        self.stop_event = Event()
        self.thread = None

    def spin(self):
        chars = "|/-\\"
        idx = 0
        while not self.stop_event.is_set():
            sys.stdout.write(f"\r{self.message} {chars[idx % len(chars)]}")
            sys.stdout.flush()
            idx += 1
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * (len(self.message) + 2) + "\r")
        sys.stdout.flush()

    def start(self):
        self.thread = Thread(target=self.spin, daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)


# ================================
# CONFIG MANAGEMENT
# ================================
def load_config() -> dict:
    default_config = {
        "max_results": DEFAULT_MAX_RESULTS,
        "exclude": ["node_modules", ".git", "__pycache__", "*.tmp"],
        "extra_folders": [],
        "apps": {},
        "history": [],
    }

    if not CONFIG_PATH.exists():
        save_config(default_config)
        return default_config

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            config = json.load(f)
            # Merge with defaults
            for key, value in default_config.items():
                if key not in config:
                    config[key] = value
            return config
    except Exception as e:
        logging.error(f"Config load failed: {e}")
        print(f"[Warning] Config load failed: {e}", file=sys.stderr)
        return default_config


def save_config(config: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)
        logging.info("Config saved")
    except Exception as e:
        logging.error(f"Config save failed: {e}")
        print(f"[Warning] Config save failed: {e}", file=sys.stderr)


def show_config(config: dict):
    print("\n" + "=" * 60)
    print("CURRENT CONFIGURATION")
    print("=" * 60)
    print(f"Max Results: {config.get('max_results', DEFAULT_MAX_RESULTS)}")
    print(f"Exclude Patterns: {', '.join(config.get('exclude', []))}")
    print(f"Extra Folders: {', '.join(config.get('extra_folders', [])) or 'None'}")
    print(f"Custom Apps: {len(config.get('apps', {}))} registered")
    print(f"Config File: {CONFIG_PATH}")
    print(f"Log File: {LOG_PATH}")
    print("=" * 60)


def edit_config_interactive(config: dict):
    print("\n=== CONFIG EDITOR ===")
    print("1) Set max results")
    print("2) Add exclusion pattern")
    print("3) Remove exclusion pattern")
    print("4) Add search folder")
    print("5) Remove search folder")
    print("6) Register app for extension")
    print("7) Reset to defaults")
    print("8) Back")

    choice = input("\nChoice: ").strip()

    if choice == "1":
        try:
            val = int(input("Max results [1-10000]: ").strip())
            if 1 <= val <= 10000:
                config["max_results"] = val
                save_config(config)
                print("✓ Updated!")
        except ValueError:
            print("Invalid number")

    elif choice == "2":
        pattern = input("Pattern (e.g., *.log, temp*, node_modules): ").strip()
        if pattern:
            config.setdefault("exclude", []).append(pattern)
            save_config(config)
            print("✓ Added!")

    elif choice == "3":
        patterns = config.get("exclude", [])
        if not patterns:
            print("No patterns to remove")
            return
        for i, p in enumerate(patterns, 1):
            print(f"{i}) {p}")
        try:
            idx = int(input("Remove #: ").strip()) - 1
            if 0 <= idx < len(patterns):
                removed = patterns.pop(idx)
                save_config(config)
                print(f"✓ Removed: {removed}")
        except (ValueError, IndexError):
            print("Invalid selection")

    elif choice == "4":
        folder = input("Folder path: ").strip()
        p = Path(folder)
        if p.exists() and p.is_dir():
            config.setdefault("extra_folders", []).append(str(p))
            save_config(config)
            print("✓ Added!")
        else:
            print("Folder doesn't exist")

    elif choice == "5":
        folders = config.get("extra_folders", [])
        if not folders:
            print("No folders to remove")
            return
        for i, f in enumerate(folders, 1):
            print(f"{i}) {f}")
        try:
            idx = int(input("Remove #: ").strip()) - 1
            if 0 <= idx < len(folders):
                removed = folders.pop(idx)
                save_config(config)
                print(f"✓ Removed: {removed}")
        except (ValueError, IndexError):
            print("Invalid selection")

    elif choice == "6":
        ext = input("Extension (e.g., .pdf): ").strip()
        app = input("App path: ").strip()
        if ext and Path(app).exists():
            config.setdefault("apps", {})[ext] = app
            save_config(config)
            print("✓ Registered!")
        else:
            print("Invalid extension or app path")

    elif choice == "7":
        confirm = input("Reset all settings? [y/N]: ").strip().lower()
        if confirm == "y":
            default = load_config.__defaults__  # Won't work, need to rewrite
            config.clear()
            config.update(
                {
                    "max_results": DEFAULT_MAX_RESULTS,
                    "exclude": ["node_modules", ".git", "__pycache__", "*.tmp"],
                    "extra_folders": [],
                    "apps": {},
                    "history": [],
                }
            )
            save_config(config)
            print("✓ Reset to defaults!")


def add_to_history(
    config: dict, mode: str, query: str, ext: Optional[str], results_count: int
):
    history = config.get("history", [])
    entry = {
        "mode": mode,
        "query": query,
        "ext": ext,
        "timestamp": time.time(),
        "results_count": results_count,
    }
    history.insert(0, entry)
    config["history"] = history[:20]  # Keep last 20
    save_config(config)
    logging.info(f"Added to history: {mode} - {query}")


def show_history(config: dict):
    history = config.get("history", [])
    if not history:
        print("\nNo search history.")
        return None

    print("\n=== SEARCH HISTORY ===")
    valid_entries = []
    for i, entry in enumerate(history[:10], 1):
        # Handle both dict and malformed entries
        if not isinstance(entry, dict):
            logging.warning(f"Skipping malformed history entry: {entry}")
            continue

        try:
            dt = datetime.fromtimestamp(entry["timestamp"]).strftime("%Y-%m-%d %H:%M")
            mode = entry["mode"].capitalize()
            query = entry["query"]
            ext = f" ({entry['ext']})" if entry.get("ext") else ""
            count = entry.get("results_count", 0)
            print(
                f"{len(valid_entries) + 1:2}) [{dt}] {mode}: {query}{ext} - {count} results"
            )
            valid_entries.append(entry)
        except (KeyError, TypeError, ValueError) as e:
            logging.warning(f"Skipping corrupted history entry: {e}")
            continue

    if not valid_entries:
        print("\nNo valid search history.")
        return None

    choice = input("\nRe-run search # (or Enter to skip): ").strip()
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(valid_entries):
            return valid_entries[idx]
    except (ValueError, IndexError):
        pass
    return None


# ================================
# TOOLS: AUTO-INSTALL
# ================================
def install_winget_tool(id: str, exe: str) -> str:
    print(f"   [Installing] {exe} via winget...")
    try:
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
        logging.info(f"Installed {exe} via winget")
    except Exception as e:
        logging.error(f"Failed to install {exe}: {e}")
        raise

    path = shutil.which(exe)
    if not path:
        sys.exit(f"[Error] {exe} not found after install.")
    return path


def install_brew_tool(name: str) -> str:
    print(f"   [Installing] {name} via brew...")
    try:
        subprocess.run(["brew", "install", name], check=True)
        logging.info(f"Installed {name} via brew")
    except Exception as e:
        logging.error(f"Failed to install {name}: {e}")
        raise
    return shutil.which(name)


def install_apt_tool(name: str) -> str:
    print(f"   [Installing] {name} via apt...")
    try:
        subprocess.run(["sudo", "apt", "update", "-qq"], check=True)
        subprocess.run(["sudo", "apt", "install", "-y", name], check=True)
        logging.info(f"Installed {name} via apt")

        # Handle fd-find -> fd alias on Linux
        if name == "fd-find":
            fd_path = shutil.which("fdfind")
            if fd_path and not shutil.which("fd"):
                # Try to create symlink
                try:
                    link_path = Path(fd_path).parent / "fd"
                    if not link_path.exists():
                        subprocess.run(
                            ["sudo", "ln", "-s", fd_path, str(link_path)], check=False
                        )
                except:
                    pass
            return shutil.which("fd") or shutil.which("fdfind")

    except Exception as e:
        logging.error(f"Failed to install {name}: {e}")
        raise

    return shutil.which(name.replace("-find", ""))


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

        # Start Everything service
        try:
            result = subprocess.run(
                ["sc", "query", "Everything"], capture_output=True, text=True
            )
            if "RUNNING" not in result.stdout:
                print("   [Starting Everything service...]")
                subprocess.run(["net", "start", "Everything"], check=False)
                time.sleep(3)
                # Verify it started
                result = subprocess.run(
                    ["sc", "query", "Everything"], capture_output=True, text=True
                )
                if "RUNNING" not in result.stdout:
                    print("   [Warning] Everything service may not be running")
        except Exception as e:
            logging.warning(f"Could not check Everything service: {e}")

        # ripgrep
        rg_path = shutil.which("rg") or install_winget_tool(
            "BurntSushi.ripgrep.MSVC", "rg"
        )

    else:  # Linux/macOS
        rg_path = shutil.which("rg") or (
            install_brew_tool("ripgrep") if IS_MACOS else install_apt_tool("ripgrep")
        )
        fd_path = (
            shutil.which("fd")
            or shutil.which("fdfind")
            or (install_brew_tool("fd") if IS_MACOS else install_apt_tool("fd-find"))
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
    except subprocess.TimeoutExpired:
        logging.warning(f"Command timeout: {' '.join(cmd)}")
        print(f"[Warning] Search timed out after {timeout}s", file=sys.stderr)
        return []
    except Exception as e:
        logging.error(f"Command failed: {e}")
        print(f"[Warning] Cmd failed: {e}", file=sys.stderr)
        return []


def get_drives() -> List[str]:
    if IS_WINDOWS:
        return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    else:
        return ["/"]


def get_file_icon(path: str) -> str:
    """Get icon label for file type"""
    ext = Path(path).suffix.lower()
    icons = {
        ".pdf": "PDF",
        ".docx": "Word",
        ".doc": "Word",
        ".xlsx": "Excel",
        ".xls": "Excel",
        ".pptx": "PPT",
        ".py": "Python",
        ".js": "JS",
        ".ts": "TS",
        ".java": "Java",
        ".cpp": "C++",
        ".c": "C",
        ".html": "HTML",
        ".css": "CSS",
        ".jpg": "Image",
        ".jpeg": "Image",
        ".png": "Image",
        ".gif": "Image",
        ".svg": "SVG",
        ".mp4": "Video",
        ".avi": "Video",
        ".mkv": "Video",
        ".mp3": "Music",
        ".wav": "Music",
        ".flac": "Music",
        ".zip": "Archive",
        ".rar": "Archive",
        ".7z": "Archive",
        ".tar": "Archive",
        ".gz": "Archive",
        ".txt": "Text",
        ".log": "Log",
        ".json": "JSON",
        ".xml": "XML",
        ".yaml": "YAML",
        ".md": "Markdown",
        ".sql": "SQL",
        ".db": "Database",
    }
    return icons.get(ext, "File")


def format_file_info(path: str) -> str:
    """Format file path with icon and size"""
    try:
        p = Path(path)
        if not p.exists():
            return f"{path} [Missing]"

        icon = get_file_icon(path)
        size = p.stat().st_size
        size_str = format_size(size)
        return f"{path} [{icon}, {size_str}]"
    except Exception as e:
        return f"{path} [Error: {e}]"


def format_size(size: int) -> str:
    """Format byte size to human readable"""
    if size < 1024:
        return f"{size}B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f}KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    else:
        return f"{size / (1024 * 1024 * 1024):.2f}GB"


def parse_size(size_str: str) -> Optional[int]:
    """Parse size string like '10mb' to bytes"""
    if not size_str:
        return None
    size_str = size_str.lower().strip()
    match = re.match(r"(\d+(?:\.\d+)?)(kb|mb|gb)?", size_str)
    if not match:
        return None
    value, unit = match.groups()
    value = float(value)
    if unit:
        value *= SIZE_UNITS.get(unit, 1)
    return int(value)


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string or relative date"""
    date_str = date_str.lower().strip()

    # Relative dates
    if date_str == "today":
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    elif date_str == "yesterday":
        return (datetime.now() - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif date_str.endswith("d"):  # e.g., "7d" = 7 days ago
        try:
            days = int(date_str[:-1])
            return datetime.now() - timedelta(days=days)
        except ValueError:
            pass

    # Absolute dates
    formats = ["%Y-%m-%d", "%Y/%m/%d", "%d-%m-%Y", "%m/%d/%Y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    return None


def fuzzy_match(user_input: str, options: List[str]) -> Optional[str]:
    """Fuzzy match user input to options"""
    user_input = user_input.lower().strip()
    for opt in options:
        if opt.lower().startswith(user_input):
            return opt
    return None


# ================================
# EXCLUDE & PATTERN
# ================================
def should_exclude(path: str, exclude: List[str]) -> bool:
    p = Path(path)
    for pattern in exclude:
        # Direct match
        if pattern in p.parts:
            return True
        # Glob match
        try:
            if p.match(pattern):
                return True
        except:
            pass
    return False


def apply_filters(path: str, filters: SearchFilters) -> bool:
    """Check if file matches size/date filters"""
    try:
        p = Path(path)
        if not p.exists() or not p.is_file():
            return True

        stat = p.stat()

        # Size filters
        if filters.min_size and stat.st_size < filters.min_size:
            return False
        if filters.max_size and stat.st_size > filters.max_size:
            return False

        # Date filters
        mtime = datetime.fromtimestamp(stat.st_mtime)
        ctime = datetime.fromtimestamp(stat.st_ctime)

        if filters.modified_after and mtime < filters.modified_after:
            return False
        if filters.modified_before and mtime > filters.modified_before:
            return False
        if filters.created_after and ctime < filters.created_after:
            return False
        if filters.created_before and ctime > filters.created_before:
            return False

        return True
    except Exception as e:
        logging.warning(f"Filter check failed for {path}: {e}")
        return True


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
def smart_search_filename(
    query: str, tools: Tools, config: dict, filters: SearchFilters
) -> List[str]:
    max_res = config.get("max_results", DEFAULT_MAX_RESULTS)
    exclude = config.get("exclude", [])
    extra_folders = config.get("extra_folders", [])
    results: List[str] = []
    scanned: Set[str] = set()

    pattern = build_everything_pattern(query)
    print(f"   Pattern → {pattern}")

    def search_path(root: Path) -> List[str]:
        if str(root) in scanned or not root.exists():
            return []
        scanned.add(str(root))

        try:
            if IS_WINDOWS:
                cmd = [
                    tools.filename_tool,
                    "-path",
                    str(root),
                    "-n",
                    str(max_res),
                    pattern,
                ]
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
            hits = [
                h
                for h in hits
                if not should_exclude(h, exclude) and apply_filters(h, filters)
            ]
            return hits
        except Exception as e:
            logging.error(f"Search failed for {root}: {e}")
            return []

    # Search common folders in parallel
    search_roots = []
    for drive in get_drives():
        user_root = (
            Path(drive) / "Users" / os.getenv("USERNAME" if IS_WINDOWS else "USER", "")
        )
        for folder in COMMON_FOLDERS:
            p = user_root / folder
            if p.exists():
                search_roots.append(p)
        for extra in extra_folders:
            p = Path(extra)
            if p.is_absolute() and p.exists():
                search_roots.append(p)

    spinner = Spinner("Searching common locations")
    spinner.start()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(search_path, root): root for root in search_roots}
        for future in as_completed(futures):
            root = futures[future]
            try:
                hits = future.result()
                results.extend(hits)
                logging.info(f"Searched {root}: {len(hits)} hits")
            except Exception as e:
                logging.error(f"Search error for {root}: {e}")

    spinner.stop()

    results = list(dict.fromkeys(results))[:max_res]
    print(f"\n   Found {len(results)} in common locations.")

    if len(results) >= max_res:
        return results

    choice = (
        input(f"   Scan full drive(s) {'/'.join(get_drives())}? [n]: ").strip().lower()
    )
    if choice not in ("y", "yes", "all"):
        return results

    spinner = Spinner("Scanning full drive(s)")
    spinner.start()

    for drive in get_drives():
        if IS_WINDOWS:
            cmd = [tools.filename_tool, "-path", drive, "-n", str(max_res), pattern]
        else:
            cmd = [tools.filename_tool, pattern, "--max-results", str(max_res)]
        hits = run_cmd(cmd, 180)
        hits = [
            h
            for h in hits
            if h not in results
            and not should_exclude(h, exclude)
            and apply_filters(h, filters)
        ]
        results.extend(hits)
        if len(results) >= max_res:
            break

    spinner.stop()
    return list(dict.fromkeys(results))[:max_res]


# ================================
# CONTENT SEARCH
# ================================
def smart_search_content(
    text: str, ext: Optional[str], tools: Tools, config: dict, filters: SearchFilters
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

    def search_path(root: Path) -> List[str]:
        if str(root) in scanned or not root.exists():
            return []
        scanned.add(str(root))

        try:
            hits = run_cmd(build_rg_cmd(str(root)), 180)
            hits = [h for h in hits if apply_filters(h, filters)]
            return hits
        except Exception as e:
            logging.error(f"Content search failed for {root}: {e}")
            return []

    search_roots = []
    for drive in get_drives():
        user_root = (
            Path(drive) / "Users" / os.getenv("USERNAME" if IS_WINDOWS else "USER", "")
        )
        for folder in COMMON_FOLDERS:
            path = user_root / folder
            if path.exists():
                search_roots.append(path)
        for extra in extra_folders:
            p = Path(extra)
            if p.is_absolute() and p.exists():
                search_roots.append(p)

    spinner = Spinner("Searching file contents")
    spinner.start()

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(search_path, root): root for root in search_roots}
        for future in as_completed(futures):
            root = futures[future]
            try:
                hits = future.result()
                results.extend(hits)
                logging.info(f"Content searched {root}: {len(hits)} hits")
            except Exception as e:
                logging.error(f"Content search error for {root}: {e}")

    spinner.stop()

    results = [r for r in results if not should_exclude(r, exclude)]
    results = list(dict.fromkeys(results))[:max_res]
    print(f"\n   Found {len(results)} in common locations.")

    if len(results) >= max_res:
        return results

    choice = input(f"   Scan full drive(s)? [n]: ").strip().lower()
    if choice not in ("y", "yes"):
        return results

    spinner = Spinner("Scanning full drive(s)")
    spinner.start()

    for drive in get_drives():
        hits = run_cmd(build_rg_cmd(drive), 600)
        hits = [
            h
            for h in hits
            if h not in results
            and not should_exclude(h, exclude)
            and apply_filters(h, filters)
        ]
        results.extend(hits)
        if len(results) >= max_res:
            break

    spinner.stop()
    return list(dict.fromkeys(results))[:max_res]


# ================================
# RESULT DISPLAY
# ================================
def display_results(results: List[str], show_details: bool = False) -> List[str]:
    if not results:
        print("\nNo results.")
        return []

    # Pre-compute formatted results
    if show_details:
        formatted = [(i, format_file_info(path)) for i, path in enumerate(results, 1)]
    else:
        formatted = [
            (i, f"{path} [{get_file_icon(path)}]") for i, path in enumerate(results, 1)
        ]

    print(f"\n{len(results)} match(es):")
    to_show = formatted[:50]
    for i, display_text in to_show:
        print(f"  {i:2}) {display_text}")

    if len(results) > 50:
        print(f"  ... and {len(results) - 50} more.")

    print("\nCommands: [numbers] select | [a]ll | [d]etails | [s]ave | [Enter] skip")
    raw = input("→ ").strip()

    if not raw:
        return []

    if raw.lower() == "a":
        print(f"   Selected all {len(results)} results")
        return results

    if raw.lower() == "d":
        return display_results(results, show_details=True)

    if raw.lower() == "s":
        export_results(results)
        return []

    selected = set()
    for part in raw.replace(" ", "").split(","):
        if "-" in part:
            try:
                s, e = part.split("-")
                s, e = int(s), int(e)
                selected.update(range(s, e + 1))
            except:
                pass
        else:
            try:
                selected.add(int(part))
            except:
                pass

    paths = [results[i - 1] for i in sorted(selected) if 1 <= i <= len(results)]
    if paths:
        print(f"   Selected {len(paths)} file(s)")
        for p in paths[:10]:
            print(f"     • {Path(p).name}")
        if len(paths) > 10:
            print(f"     ... and {len(paths) - 10} more")

    return paths


def export_results(results: List[str]):
    """Export results to file"""
    print("\nExport format:")
    print("  1) Text file (.txt)")
    print("  2) CSV file (.csv)")
    print("  3) JSON file (.json)")

    choice = input("Choice [1]: ").strip() or "1"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    try:
        if choice == "1":
            filename = f"search_results_{timestamp}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                for path in results:
                    f.write(f"{path}\n")
            print(f"✓ Exported to {filename}")

        elif choice == "2":
            filename = f"search_results_{timestamp}.csv"
            with open(filename, "w", encoding="utf-8", newline="") as f:
                f.write("Path,Size,Modified,Type\n")
                for path in results:
                    try:
                        p = Path(path)
                        if p.exists():
                            stat = p.stat()
                            size = stat.st_size
                            mtime = datetime.fromtimestamp(stat.st_mtime).strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                            ftype = get_file_icon(path)
                            f.write(f'"{path}",{size},"{mtime}","{ftype}"\n')
                    except:
                        f.write(f'"{path}",,,\n')
            print(f"✓ Exported to {filename}")

        elif choice == "3":
            filename = f"search_results_{timestamp}.json"
            data = []
            for path in results:
                try:
                    p = Path(path)
                    if p.exists():
                        stat = p.stat()
                        data.append(
                            {
                                "path": path,
                                "size": stat.st_size,
                                "modified": datetime.fromtimestamp(
                                    stat.st_mtime
                                ).isoformat(),
                                "type": get_file_icon(path),
                            }
                        )
                    else:
                        data.append({"path": path, "exists": False})
                except:
                    data.append({"path": path, "error": True})

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            print(f"✓ Exported to {filename}")

    except Exception as e:
        print(f"✗ Export failed: {e}")


def preview_file(path: str):
    """Show preview of text file"""
    try:
        p = Path(path)
        if not p.exists():
            print("   File not found")
            return

        if p.stat().st_size > 1024 * 1024:  # 1MB
            print("   File too large to preview")
            return

        ext = p.suffix.lower()
        text_exts = [
            ".txt",
            ".log",
            ".md",
            ".py",
            ".js",
            ".json",
            ".xml",
            ".html",
            ".css",
            ".yaml",
            ".ini",
            ".conf",
        ]

        if ext not in text_exts:
            print("   Not a text file")
            return

        print("\n" + "─" * 60)
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()[:30]  # First 30 lines
            for line in lines:
                print(line.rstrip())
        if len(lines) >= 30:
            print("...")
        print("─" * 60)

    except Exception as e:
        print(f"   Preview failed: {e}")


# ================================
# ACTION MENU
# ================================
def post_action_menu(paths: List[str], config: dict):
    if not paths:
        return

    apps = config.get("apps", {})

    for idx, path in enumerate(paths, 1):
        if not Path(path).exists():
            print(f"\n[{idx}/{len(paths)}] {path}")
            print("   ✗ File not found - skipping")
            continue

        ext = Path(path).suffix.lower()
        app = apps.get(ext)

        while True:
            print(f"\n[{idx}/{len(paths)}] {format_file_info(path)}")
            print(
                "  Actions: [o]pen [f]older [c]opy [p]review [d]elete [q]uit [Enter=next]"
            )
            choice = input("  → ").strip().lower()

            # Fuzzy match
            matched = fuzzy_match(
                choice, ["open", "folder", "copy", "preview", "delete", "quit"]
            )
            if matched:
                choice = matched[0]  # First letter

            if choice == "q":
                print("   ⏭ Skipped remaining files")
                return

            if choice in ("o", ""):
                try:
                    if app:
                        subprocess.Popen([app, path])
                    elif IS_WINDOWS:
                        os.startfile(path)
                    else:
                        subprocess.run(["open" if IS_MACOS else "xdg-open", path])
                    print("   ✓ Opened")
                    break  # Move to next file
                except Exception as e:
                    print(f"   ✗ Open failed: {e}")

            elif choice == "f":
                try:
                    folder = str(Path(path).parent)
                    if IS_WINDOWS:
                        os.startfile(folder)
                    else:
                        subprocess.run(["open" if IS_MACOS else "xdg-open", folder])
                    print("   ✓ Folder opened")
                    break
                except Exception as e:
                    print(f"   ✗ Failed: {e}")

            elif choice == "c":
                try:
                    import pyperclip

                    pyperclip.copy(path)
                    print("   ✓ Path copied to clipboard!")
                    break
                except ImportError:
                    print(f"   Path: {path}")
                    print("   (Install pyperclip for clipboard support)")
                    break

            elif choice == "p":
                preview_file(path)
                # Stay in loop to allow more actions

            elif choice == "d":
                confirm = input("   Delete this file? [y/N]: ").strip().lower()
                if confirm == "y":
                    try:
                        Path(path).unlink()
                        print("   ✓ Deleted")
                        break
                    except Exception as e:
                        print(f"   ✗ Delete failed: {e}")
                else:
                    print("   Cancelled")

            else:
                print("   Unknown command")


# ================================
# PARSE FILTERS
# ================================
def parse_filters_from_args(args) -> SearchFilters:
    """Parse filter arguments"""
    filters = SearchFilters()

    if args.min_size:
        filters.min_size = parse_size(args.min_size)
    if args.max_size:
        filters.max_size = parse_size(args.max_size)
    if args.modified_after:
        filters.modified_after = parse_date(args.modified_after)
    if args.modified_before:
        filters.modified_before = parse_date(args.modified_before)
    if args.created_after:
        filters.created_after = parse_date(args.created_after)
    if args.created_before:
        filters.created_before = parse_date(args.created_before)

    # Quick filters
    if args.today:
        filters.modified_after = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    if args.large:
        filters.min_size = 100 * 1024 * 1024  # 100MB
    if args.recent:
        filters.modified_after = datetime.now() - timedelta(days=args.recent)

    return filters


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
    print("  3) Search history")
    print("  4) Config settings")
    print("  5) Exit")

    choice = input("\nPick [1]: ").strip() or "1"

    if choice == "3":
        entry = show_history(config)
        if entry:
            return entry["mode"], entry["query"], entry.get("ext")
        else:
            return interactive_menu(tools, config)

    elif choice == "4":
        show_config(config)
        edit_choice = input("\n[e]dit config or [Enter] to continue: ").strip().lower()
        if edit_choice == "e":
            edit_config_interactive(config)
        return interactive_menu(tools, config)

    elif choice == "5":
        clear_screen()
        sys.exit(0)

    elif choice == "2":
        text = input("\nText to find: ").strip()
        if not text:
            print("Text required!")
            time.sleep(1)
            return interactive_menu(tools, config)
        ext = input("File type (e.g., py, txt) [all]: ").strip() or None
        return "content", text, ext

    else:
        query = input("\nFilename pattern: ").strip()
        if not query:
            print("Query required!")
            time.sleep(1)
            return interactive_menu(tools, config)
        return "filename", query, None


# ================================
# MAIN
# ================================
def main():
    parser = argparse.ArgumentParser(
        description="Fast File & Content Search Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Search mode
    parser.add_argument("query", nargs="?", help="Search query")
    parser.add_argument("--content", action="store_true", help="Search file contents")
    parser.add_argument("--ext", help="File extension filter")

    # Config management
    parser.add_argument(
        "--config", choices=["show", "edit", "reset"], help="Manage configuration"
    )
    parser.add_argument("--exclude-add", help="Add exclusion pattern")
    parser.add_argument("--folder-add", help="Add search folder")
    parser.add_argument("--max-results", type=int, help="Set max results")

    # Filters
    parser.add_argument("--min-size", help="Minimum file size (e.g., 10mb)")
    parser.add_argument("--max-size", help="Maximum file size (e.g., 100mb)")
    parser.add_argument(
        "--modified-after", help="Modified after date (YYYY-MM-DD or '7d')"
    )
    parser.add_argument("--modified-before", help="Modified before date")
    parser.add_argument("--created-after", help="Created after date")
    parser.add_argument("--created-before", help="Created before date")

    # Quick filters
    parser.add_argument("--today", action="store_true", help="Modified today")
    parser.add_argument("--large", action="store_true", help="Files >100MB")
    parser.add_argument(
        "--recent", type=int, metavar="DAYS", help="Modified in last N days"
    )

    # Other
    parser.add_argument("--no-clear", action="store_true", help="Don't clear screen")
    parser.add_argument("--history", action="store_true", help="Show search history")
    parser.add_argument("--version", action="version", version=f"v{VERSION}")

    args = parser.parse_args()

    # Load config
    config = load_config()

    # Handle config commands
    if args.config:
        if args.config == "show":
            show_config(config)
            sys.exit(0)
        elif args.config == "edit":
            edit_config_interactive(config)
            sys.exit(0)
        elif args.config == "reset":
            config.clear()
            config.update(load_config())
            print("✓ Config reset to defaults")
            sys.exit(0)

    if args.exclude_add:
        config.setdefault("exclude", []).append(args.exclude_add)
        save_config(config)
        print(f"✓ Added exclusion: {args.exclude_add}")
        sys.exit(0)

    if args.folder_add:
        p = Path(args.folder_add)
        if p.exists() and p.is_dir():
            config.setdefault("extra_folders", []).append(str(p))
            save_config(config)
            print(f"✓ Added folder: {args.folder_add}")
        else:
            print(f"✗ Folder doesn't exist: {args.folder_add}")
        sys.exit(0)

    if args.max_results:
        config["max_results"] = args.max_results
        save_config(config)
        print(f"✓ Max results set to {args.max_results}")
        sys.exit(0)

    if args.history:
        show_history(config)
        sys.exit(0)

    # Ensure tools are installed
    tools = ensure_tools()
    clear_enabled = not args.no_clear

    # Parse filters
    filters = parse_filters_from_args(args)

    # Determine search mode
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

    print(f"\n{'=' * 60}")
    print(f"Searching: {query}")
    if ext:
        print(f"Extension: {ext}")
    if filters.min_size or filters.max_size:
        print(
            f"Size: {format_size(filters.min_size or 0)} - {format_size(filters.max_size or float('inf'))}"
        )
    if filters.modified_after or filters.modified_before:
        print(
            f"Modified: {filters.modified_after or 'any'} - {filters.modified_before or 'any'}"
        )
    print(f"{'=' * 60}")

    results = []
    try:
        if mode == "filename":
            results = smart_search_filename(query, tools, config, filters)
        else:
            results = smart_search_content(query, ext, tools, config, filters)
    except KeyboardInterrupt:
        print("\n\n[Cancelled]")
        sys.exit(0)
    except Exception as e:
        logging.error(f"Search failed: {e}")
        print(f"\n[Error] Search failed: {e}")
        sys.exit(1)

    # Add to history
    add_to_history(config, mode, query, ext, len(results))

    selected = display_results(results)
    post_action_menu(selected, config)

    print("\n" + "=" * 60)
    another = input("Search again? [Y/n]: ").strip().lower()
    if another not in ("n", "no"):
        main()
    else:
        clear_screen()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen()
        sys.exit(0)
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
        print(f"\n[Fatal Error] {e}")
        print(f"Check log: {LOG_PATH}")
        sys.exit(1)
