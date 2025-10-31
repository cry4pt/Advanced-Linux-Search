#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Fast File & Content Search Tool
- Everything (filename) + ripgrep (content)
- Auto-install via winget
- Smart folder + full drive scanning
- Open multiple files by number/range
- Configurable via ~/.fastsearch.json
"""

import os
import sys
import shutil
import subprocess
import argparse
import string
import time
import json
from pathlib import Path
from typing import List, Optional, Tuple, Set

# ================================
# CONFIGURATION
# ================================
VERSION = "1.0.0"
DEFAULT_MAX_RESULTS = 500
CLEAR_SCREEN_DEFAULT = True

COMMON_FOLDERS_PER_DRIVE = [
    "Desktop",
    "Documents",
    "Downloads",
    "Pictures",
    "Videos",
    "Music",
    "OneDrive",
]

CONFIG_PATH = Path.home() / ".fastsearch.json"


# ================================
# CONFIG LOADER
# ================================
def load_config() -> dict:
    """Load user config if exists."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"   [Warning] Failed to load config {CONFIG_PATH}: {e}", file=sys.stderr)
        return {}


def get_max_results() -> int:
    config = load_config()
    return config.get("max_results", DEFAULT_MAX_RESULTS)


def get_extra_folders() -> List[str]:
    config = load_config()
    return config.get("extra_folders", [])


# ================================
# TOOL INSTALLERS
# ================================
def has_winget() -> bool:
    return shutil.which("winget") is not None


def find_es_path() -> Optional[str]:
    """Find es.exe in PATH or common install locations."""
    path = shutil.which("es.exe")
    if path:
        return path

    candidates = [
        Path(r"C:\Program Files\Everything\es.exe"),
        Path(r"C:\Program Files (x86)\Everything\es.exe"),
        Path(os.getenv("LOCALAPPDATA", "")) / "Programs" / "Everything" / "es.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def ensure_everything_service():
    """Ensure Everything service is running."""
    print("   [Checking] Everything service...")
    try:
        result = subprocess.run(
            ["sc", "query", "Everything"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        if "RUNNING" not in result.stdout:
            print("   [Starting] Everything service...")
            subprocess.run(["net", "start", "Everything"], check=False, timeout=10)
            print("   Waiting 5s for indexing...")
            time.sleep(5)
    except Exception as e:
        print(f"   [Warning] Could not start Everything service: {e}")


def install_everything() -> str:
    """Install Everything via winget and return es.exe path."""
    try:
        print("   [Installing] Everything via winget...")
        subprocess.run(
            [
                "winget",
                "install",
                "--id",
                "voidtools.Everything",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            check=True,
            timeout=300,
        )
        es_path = find_es_path()
        if not es_path:
            sys.exit("[Error] es.exe not found after installation.")
        ensure_everything_service()
        return es_path
    except subprocess.CalledProcessError as e:
        sys.exit(f"[Error] winget failed: {e}")
    except Exception as e:
        sys.exit(f"[Error] Installation failed: {e}")


def install_ripgrep() -> str:
    """Install ripgrep via winget."""
    try:
        print("   [Installing] ripgrep via winget...")
        subprocess.run(
            [
                "winget",
                "install",
                "--id",
                "BurntSushi.ripgrep.MSVC",
                "--silent",
                "--accept-package-agreements",
                "--accept-source-agreements",
            ],
            check=True,
            timeout=300,
        )
        rg_path = shutil.which("rg")
        if not rg_path:
            sys.exit("[Error] rg not found after install.")
        return rg_path
    except Exception as e:
        sys.exit(f"[Error] ripgrep install failed: {e}")


def ensure_tools() -> Tuple[str, str]:
    """Ensure both tools are installed and return paths."""
    if not has_winget():
        sys.exit("[Error] winget not found. Install from Microsoft Store.")

    es_path = find_es_path()
    rg_path = shutil.which("rg")

    if not es_path:
        es_path = install_everything()
    else:
        print(f"   [OK] Everything found: {es_path}")
        ensure_everything_service()

    if not rg_path:
        rg_path = install_ripgrep()
    else:
        print(f"   [OK] ripgrep found: {rg_path}")

    return es_path, rg_path


# ================================
# UTILS
# ================================
def clear_screen(enabled: bool = True):
    if enabled:
        os.system("cls" if os.name == "nt" else "clear")


def run_cmd(cmd, timeout=60) -> List[str]:
    """Run command with UTF-8 safety and error handling."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
        lines = result.stdout.strip().splitlines()
        return [line.strip() for line in lines if line.strip()]
    except subprocess.TimeoutExpired:
        print(f"   [Timeout] Command timed out after {timeout}s", file=sys.stderr)
        return []
    except Exception as e:
        print(f"   [Warning] Command failed: {e}", file=sys.stderr)
        return []


def get_drives() -> List[str]:
    """Detect all available local drives."""
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def dedup_results(results: List[str]) -> List[str]:
    """Remove duplicates while preserving order."""
    seen = set()
    deduped = []
    for r in results:
        if r not in seen:
            seen.add(r)
            deduped.append(r)
    return deduped


# ================================
# 1) Everything – Smart Filename Search
# ================================
def build_everything_pattern(user_input: str) -> str:
    s = user_input.strip()
    if not s:
        return "*"

    if "." in s and "/" not in s and "*" not in s and "?" not in s:
        return s  # exact: report.pdf

    if "*" in s or "?" in s:
        return s  # glob

    if "/" in s:
        name, ext = s.split("/", 1)
        ext = ext.lstrip(".")
        return f"*{name}*.{ext}" if ext else f"*{name}*"

    return f"*{s}*"  # fuzzy


def smart_search_everything(
    pattern: str, es_path: str, use_regex: bool = False
) -> List[str]:
    pattern = build_everything_pattern(pattern)
    print(f"   Pattern → {pattern}")

    results = []
    drives = get_drives()
    common_scanned = set()
    extra_folders = get_extra_folders()
    max_res = get_max_results()

    print("   Scanning common folders + extras...")

    for drive in drives:
        user_root = Path(drive) / "Users" / os.getenv("USERNAME", "")
        public_root = Path("C:\\Users\\Public") if drive == "C:\\" else None

        for folder in COMMON_FOLDERS_PER_DRIVE + ["Public"]:
            user_path = user_root / folder
            if user_path.exists() and str(user_path) not in common_scanned:
                print(f"   → {user_path}")
                common_scanned.add(str(user_path))
                cmd = [es_path, "-path", str(user_path), "-n", str(max_res), pattern]
                if use_regex:
                    cmd.insert(-1, "-regex")
                hits = run_cmd(cmd, timeout=30)
                results.extend(hits)
                if hits:
                    print(f"     Found {len(hits)} match(es)")

            if (
                public_root
                and folder == "Public"
                and str(public_root) not in common_scanned
            ):
                print(f"   → {public_root}")
                common_scanned.add(str(public_root))
                cmd = [es_path, "-path", str(public_root), "-n", str(max_res), pattern]
                if use_regex:
                    cmd.insert(-1, "-regex")
                hits = run_cmd(cmd, timeout=30)
                results.extend(hits)
                if hits:
                    print(f"     Found {len(hits)} match(es)")

        for extra in extra_folders:
            p = Path(extra)
            if p.is_absolute() and p.exists() and str(p) not in common_scanned:
                print(f"   → {p}")
                common_scanned.add(str(p))
                cmd = [es_path, "-path", str(p), "-n", str(max_res), pattern]
                if use_regex:
                    cmd.insert(-1, "-regex")
                hits = run_cmd(cmd, timeout=30)
                results.extend(hits)
                if hits:
                    print(f"     Found {len(hits)} match(es)")

        if len(results) >= max_res:
            break

    results = dedup_results(results)
    print(f"\n   Common scan complete: {len(results)} match(es)")

    if len(results) >= max_res:
        return results[:max_res]

    # Prompt for full drive scan
    c_exists = "C:\\" in drives
    d_exists = "D:\\" in drives
    options = []
    if c_exists:
        options.append("c")
    if d_exists:
        options.append("d")
    both = "both" if c_exists and d_exists else None

    prompt = "   Scan full drive"
    if len(options) == 1:
        prompt += f" {options[0].upper()}:\\"
    else:
        prompt += f" (c/d/{'both/' if both else ''}n)"
    prompt += "? [n]: "

    choice = input(prompt).strip().lower()
    if choice not in options and choice != "both" and choice not in ("y", "yes"):
        print("   Full scan skipped.")
        return results[:max_res]

    to_scan = []
    if choice == "c":
        to_scan = ["C:\\"]
    elif choice == "d":
        to_scan = ["D:\\"]
    elif choice in ("both", "y", "yes") and both:
        to_scan = drives
    else:
        to_scan = [drives[0]]

    print(f"   Scanning full drive(s): {', '.join(to_scan)}...")
    for root in to_scan:
        cmd = [es_path, "-path", root, "-n", str(max_res), pattern]
        if use_regex:
            cmd.insert(-1, "-regex")
        hits = run_cmd(cmd, timeout=90)
        results.extend(hits)
        if len(results) >= max_res:
            break

    return dedup_results(results)[:max_res]


# ================================
# 2) Ripgrep – Smart Content Search
# ================================
def smart_content_search_rg(
    text: str, file_ext: Optional[str], rg_path: str
) -> List[str]:
    if not text.strip():
        return []

    file_glob = None
    if file_ext:
        ext = file_ext.strip().lstrip(".")
        file_glob = f"*.{ext}" if ext else "*"

    def build_cmd(root):
        cmd = [
            rg_path,
            "--files-with-matches",
            "--no-messages",
            "--ignore-case",
            "--max-columns",
            "200",
            "--follow",
            text,
        ]
        if file_glob:
            cmd.extend(["--glob", file_glob])
        cmd.append(str(root))
        return cmd

    results = []
    drives = get_drives()
    common_scanned = set()
    extra_folders = get_extra_folders()
    max_res = get_max_results()

    print("   Scanning common folders + extras...")

    for drive in drives:
        user_root = Path(drive) / "Users" / os.getenv("USERNAME", "")
        public_root = Path("C:\\Users\\Public") if drive == "C:\\" else None

        for folder in COMMON_FOLDERS_PER_DRIVE:
            user_path = user_root / folder
            if user_path.exists() and str(user_path) not in common_scanned:
                print(f"   → {user_path}")
                common_scanned.add(str(user_path))
                hits = run_cmd(build_cmd(user_path), timeout=180)
                results.extend(hits)
                if hits:
                    print(f"     Found {len(hits)} match(es)")

            if (
                public_root
                and folder == "Public"
                and str(public_root) not in common_scanned
            ):
                print(f"   → {public_root}")
                common_scanned.add(str(public_root))
                hits = run_cmd(build_cmd(public_root), timeout=180)
                results.extend(hits)
                if hits:
                    print(f"     Found {len(hits)} match(es)")

        for extra in extra_folders:
            p = Path(extra)
            if p.is_absolute() and p.exists() and str(p) not in common_scanned:
                print(f"   → {p}")
                common_scanned.add(str(p))
                hits = run_cmd(build_cmd(p), timeout=180)
                results.extend(hits)
                if hits:
                    print(f"     Found {len(hits)} match(es)")

        if len(results) >= max_res:
            break

    results = dedup_results(results)
    print(f"\n   Common scan complete: {len(results)} match(es)")

    if len(results) >= max_res:
        return results[:max_res]

    # Full drive scan prompt
    c_exists = "C:\\" in drives
    d_exists = "D:\\" in drives
    options = ["c"] if c_exists else []
    if d_exists:
        options.append("d")
    both = "both" if c_exists and d_exists else None

    prompt = "   Scan full drive"
    if len(options) == 1:
        prompt += f" {options[0].upper()}:\\"
    else:
        prompt += f" (c/d/{'both/' if both else ''}n)"
    prompt += "? [n]: "

    choice = input(prompt).strip().lower()
    if choice not in options and choice != "both" and choice not in ("y", "yes"):
        print("   Full scan skipped.")
        return results[:max_res]

    to_scan = ["C:\\"] if choice == "c" else ["D:\\"] if choice == "d" else drives
    if choice in ("both", "y", "yes") and both:
        to_scan = drives

    print(f"   Scanning full drive(s): {', '.join(to_scan)}...")
    for root in to_scan:
        hits = run_cmd(build_cmd(root), timeout=600)
        results.extend(hits)
        if len(results) >= max_res:
            break

    return dedup_results(results)[:max_res]


# ================================
# Interactive Menu & Result Viewer
# ================================
def interactive_menu() -> Tuple[str, str, Optional[str]]:
    clear_screen(True)
    print("=" * 60)
    print("           FAST FILE & CONTENT SEARCH")
    print(f"                   v{VERSION}")
    print("=" * 60)
    print("  1) Filename search – Everything (fast indexing)")
    print("  2) Text inside files – ripgrep (ultra-fast grep)")

    choice = input("\nPick [1-2]: ").strip() or "1"
    if choice == "2":
        text = input("\nText to find inside files: ").strip()
        if not text:
            input("   [Error] Text required. Press Enter...")
            return interactive_menu()
        ext = input("File type (e.g. txt, py, log) [all]: ").strip()
        return "content", text, ext or None
    else:
        query = input("\nFilename pattern (e.g. report, inv/pdf, *.log): ").strip()
        if not query:
            input("   [Error] Pattern required. Press Enter...")
            return interactive_menu()
        return "everything", query, None


def display_results(results: List[str]) -> List[str]:
    """Show results and return list of paths to open (supports ranges)."""
    if not results:
        print("\nNo results found.")
        return []

    to_open: List[str] = []
    print(f"\nFound {len(results)} match(es):")
    shown = results[:50]
    for i, r in enumerate(shown, 1):
        print(f"  {i:2}) {r}")

    if len(results) > 50:
        print(f"  ... and {len(results) - 50} more.")

    raw = input(
        "\nEnter number(s) to open (e.g. 1,3-5,7) or [Enter] to continue: "
    ).strip()
    if not raw:
        return []

    numbers: Set[int] = set()
    for part in raw.replace(" ", "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part and part.count("-") == 1:
            start_str, end_str = part.split("-")
            try:
                start, end = int(start_str), int(end_str)
                if 1 <= start <= end <= len(results):
                    numbers.update(range(start, end + 1))
            except ValueError:
                continue
        else:
            try:
                num = int(part)
                if 1 <= num <= len(results):
                    numbers.add(num)
            except ValueError:
                continue

    if not numbers:
        print("   [Warning] No valid numbers entered.")
        return []

    for n in sorted(numbers):
        idx = n - 1
        path = results[idx]
        to_open.append(path)
        print(f"   Queued: {n}) {path}")

    return to_open


# ================================
# CLI Parser
# ================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Fast search: Everything + ripgrep (auto-install via winget)",
        epilog="Run without args → interactive menu",
    )
    parser.add_argument("pattern", nargs="?", help="File pattern or search text")
    parser.add_argument("--content", action="store_true", help="Search inside files")
    parser.add_argument("--text", help="Text to search inside files")
    parser.add_argument("--ext", help="File extension filter")
    parser.add_argument("--regex", action="store_true", help="Use regex in Everything")
    parser.add_argument("--no-clear", action="store_true", help="Disable screen clear")
    parser.add_argument(
        "--list-drives", action="store_true", help="List drives and exit"
    )
    parser.add_argument(
        "-v", "--version", action="version", version=f"FastSearch {VERSION}"
    )
    return parser.parse_args()


# ================================
# Main
# ================================
def main():
    args = parse_args()
    clear_enabled = not args.no_clear

    if args.list_drives:
        print("Detected drives:", ", ".join(get_drives()))
        return

    # Auto-install tools
    es_path, rg_path = ensure_tools()

    # Resolve mode
    if not args.pattern and not args.content and not args.text:
        mode, query, file_ext = interactive_menu()
        use_regex = False
    else:
        file_ext = args.ext
        use_regex = args.regex
        if args.content or args.text:
            mode = "content"
            query = args.text or args.pattern
            if not query:
                print("   [Error] --text or pattern required for content search.")
                sys.exit(1)
        else:
            mode = "everything"
            query = args.pattern
            if not query:
                print("   [Error] Pattern required for filename search.")
                sys.exit(1)

    clear_screen(clear_enabled)
    print(
        f"\nMode: {'ripgrep (content)' if mode == 'content' else 'Everything (filename)'}"
    )
    if file_ext:
        print(f"Filter: *.{file_ext.strip('.')}")

    # Execute
    results = []
    if mode == "everything":
        print(f"\nSearching filenames: {query}")
        results = smart_search_everything(query, es_path, use_regex)
    else:
        print(f"\nSearching inside files: {query!r}")
        results = smart_content_search_rg(query, file_ext, rg_path)

    # Show and interact
    to_open = display_results(results)
    for path in to_open:
        try:
            os.startfile(path)
            print(f"   Opened: {path}")
        except Exception as e:
            print(f"   [Error] Could not open {path}: {e}")

    input("\nPress Enter to search again...")
    main()


# ================================
# Entry Point
# ================================
if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        clear_screen(CLEAR_SCREEN_DEFAULT)
        sys.exit(0)
