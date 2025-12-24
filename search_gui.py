#!/usr/bin/env python3
"""
Advanced Search Tool - GUI Version
PyQt5 interface for the advanced search tool
"""

import sys
import os
import subprocess
import json
import re
import platform
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QTextEdit, QLabel, QComboBox, QCheckBox,
    QSpinBox, QGroupBox, QSplitter, QFileDialog, QTabWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QStatusBar, QProgressBar, QMessageBox,
    QListWidget, QListWidgetItem, QSizePolicy, QDateEdit, QDoubleSpinBox
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QDate
from PyQt5.QtGui import QFont, QColor, QTextCursor, QTextCharFormat, QSyntaxHighlighter

# Import the backend search class - MERGED FROM advanced_search.py
from collections import defaultdict

# Platform detection
IS_WINDOWS = platform.system() == "Windows"
IS_MACOS = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"

# Common folders to search (smart locations)
COMMON_FOLDERS = [
    "Desktop", "Documents", "Downloads", "Pictures", 
    "Videos", "Music", "OneDrive", "Google Drive", "Dropbox"
]

def get_smart_locations() -> List[Path]:
    """Get smart search locations (Desktop, Documents, etc.)"""
    locations = []
    
    if IS_WINDOWS:
        username = os.getenv('USERNAME', '')
        user_profile = Path(os.getenv('USERPROFILE', ''))
        
        for folder in COMMON_FOLDERS:
            path = user_profile / folder
            if path.exists():
                locations.append(path)
    else:
        username = os.getenv('USER', '')
        user_home = Path.home()
        
        for folder in COMMON_FOLDERS:
            path = user_home / folder
            if path.exists():
                locations.append(path)
    
    return locations

class AdvancedSearch:
    """Advanced search backend using ripgrep - MERGED FROM advanced_search.py"""
    def __init__(self):
        self.rg_path = self._find_ripgrep()
        
    def _find_ripgrep(self) -> str:
        """Find ripgrep executable"""
        import platform
        try:
            startupinfo = None
            creationflags = 0
            if platform.system() == 'Windows':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            
            result = subprocess.run(
                ['where' if platform.system() == 'Windows' else 'which', 'rg'], 
                capture_output=True, 
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            if result.returncode == 0:
                return 'rg'
        except:
            pass
        
        # Try common paths
        common_paths = [
            r"C:\Program Files\ripgrep\rg.exe",
            r"C:\tools\ripgrep\rg.exe",
            str(Path.home() / "scoop" / "shims" / "rg.exe"),
        ]
        
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return 'rg'  # Fallback
    
    def search(self, pattern: str, path: str = ".", **kwargs) -> List[Dict]:
        """Main search function with intelligent options"""
        cmd = [self.rg_path]
        
        # Core options for structured output
        cmd.extend(['--json', '--line-number'])
        
        # Smart case sensitivity
        if kwargs.get('smart_case', True) and pattern.islower():
            cmd.append('--smart-case')
        elif kwargs.get('case_insensitive', False):
            cmd.append('--ignore-case')
        
        # Context lines
        if kwargs.get('context'):
            cmd.extend(['-C', str(kwargs['context'])])
        if kwargs.get('before'):
            cmd.extend(['-B', str(kwargs['before'])])
        if kwargs.get('after'):
            cmd.extend(['-A', str(kwargs['after'])])
        
        # File filtering
        if kwargs.get('type'):
            for t in kwargs['type']:
                cmd.extend(['-t', t])
        if kwargs.get('glob'):
            for g in kwargs['glob']:
                cmd.extend(['-g', g])
        
        # Advanced patterns
        if kwargs.get('multiline'):
            cmd.append('--multiline')
        if kwargs.get('word_boundary'):
            cmd.append('--word-regexp')
        if kwargs.get('fixed_strings'):
            cmd.append('--fixed-strings')
        
        # Performance
        if kwargs.get('hidden'):
            cmd.append('--hidden')
        if kwargs.get('no_ignore'):
            cmd.append('--no-ignore')
        
        # Stats
        if kwargs.get('stats'):
            cmd.append('--stats')
        
        # Max results
        if kwargs.get('max_count'):
            cmd.extend(['--max-count', str(kwargs['max_count'])])
        
        cmd.extend([pattern, path])
        
        # Suppress CMD window on Windows
        startupinfo = None
        creationflags = 0
        if IS_WINDOWS:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        
        try:
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            return self._parse_json_output(result.stdout)
        except Exception as e:
            print(f"❌ Search failed: {e}")
            return []
    
    def _parse_json_output(self, output: str) -> List[Dict]:
        """Parse ripgrep JSON output"""
        results = []
        current_file = None
        
        for line in output.strip().split('\n'):
            if not line:
                continue
            
            try:
                data = json.loads(line)
                msg_type = data.get('type')
                
                if msg_type == 'begin':
                    current_file = data['data']['path']['text']
                elif msg_type == 'match':
                    match_data = data['data']
                    results.append({
                        'file': current_file,
                        'line_num': match_data['line_number'],
                        'line': match_data['lines']['text'].rstrip('\n'),
                        'submatches': match_data.get('submatches', []),
                    })
            except json.JSONDecodeError:
                continue
        
        return results
    
    def search_multiple_patterns(self, patterns: List[str], path: str = ".", 
                                  operator: str = "AND", **kwargs) -> List[Dict]:
        """Search for multiple patterns with AND/OR logic"""
        if operator == "OR":
            # Combine patterns with |
            combined = '|'.join(f'({p})' for p in patterns)
            return self.search(combined, path, **kwargs)
        else:  # AND
            # Search for first pattern, then filter results
            results = self.search(patterns[0], path, **kwargs)
            
            import re
            for pattern in patterns[1:]:
                filtered = []
                for result in results:
                    if re.search(pattern, result['line'], re.IGNORECASE if kwargs.get('case_insensitive') else 0):
                        filtered.append(result)
                results = filtered
            
            return results
    
    def find_definition(self, symbol: str, path: str = ".", lang: str = None) -> List[Dict]:
        """Find where a symbol is defined"""
        patterns = {
            'python': [
                fr'^\s*def\s+{symbol}\s*\(',
                fr'^\s*class\s+{symbol}\s*[:\(]',
                fr'^{symbol}\s*=',
            ],
            'javascript': [
                fr'function\s+{symbol}\s*\(',
                fr'const\s+{symbol}\s*=',
                fr'let\s+{symbol}\s*=',
                fr'class\s+{symbol}\s*{{',
            ],
            'csharp': [
                fr'(public|private|protected|internal)\s+.*\s+{symbol}\s*\(',
                fr'(public|private|protected|internal)\s+class\s+{symbol}',
                fr'(public|private|protected|internal)\s+.*\s+{symbol}\s*{{',
            ],
            'go': [
                fr'func\s+{symbol}\s*\(',
                fr'type\s+{symbol}\s+struct',
            ],
        }
        
        if lang and lang in patterns:
            combined = '|'.join(f'({p})' for p in patterns[lang])
        else:
            # Try all patterns
            all_patterns = []
            for lang_patterns in patterns.values():
                all_patterns.extend(lang_patterns)
            combined = '|'.join(f'({p})' for p in all_patterns)
        
        return self.search(combined, path, multiline=False)
    
    def find_usages(self, symbol: str, path: str = ".", **kwargs) -> List[Dict]:
        """Find all usages of a symbol"""
        return self.search(rf'\b{symbol}\b', path, word_boundary=True, **kwargs)
    
    def find_todos(self, path: str = ".", include_fixme: bool = True) -> List[Dict]:
        """Find TODO and FIXME comments"""
        pattern = r'TODO|FIXME' if include_fixme else r'TODO'
        return self.search(pattern, path, case_insensitive=True)

class SearchWorker(QThread):
    """Worker thread for running searches in background"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    progress = pyqtSignal(int, int)
    
    def __init__(self, searcher, search_func, *args, **kwargs):
        super().__init__()
        self.searcher = searcher
        self.search_func = search_func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        try:
            results = self.search_func(*self.args, **self.kwargs)
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))

class FilenameSearchWorker(QThread):
    """Worker thread for FAST filename search using ripgrep"""
    finished = pyqtSignal(list)
    error = pyqtSignal(str)
    
    def __init__(self, pattern, directories=None, min_size=None, max_size=None, 
                 modified_after=None, modified_before=None, use_smart_locations=True):
        super().__init__()
        self.pattern = pattern
        self.directories = directories or []
        self.min_size = min_size
        self.max_size = max_size
        self.modified_after = modified_after
        self.modified_before = modified_before
        self.use_smart_locations = use_smart_locations
        self.rg_path = self._find_ripgrep()
    
    def _find_ripgrep(self):
        """Find ripgrep executable"""
        try:
            startupinfo = None
            creationflags = 0
            if IS_WINDOWS:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE
                creationflags = subprocess.CREATE_NO_WINDOW
            
            result = subprocess.run(
                ['where' if IS_WINDOWS else 'which', 'rg'], 
                capture_output=True, 
                text=True,
                startupinfo=startupinfo,
                creationflags=creationflags
            )
            if result.returncode == 0:
                return 'rg'
        except:
            pass
        return 'rg'
    
    def _apply_filters(self, filepath: str) -> bool:
        """Apply size and date filters"""
        try:
            stat = os.stat(filepath)
            
            # Size filter
            if self.min_size and stat.st_size < self.min_size:
                return False
            if self.max_size and stat.st_size > self.max_size:
                return False
            
            # Date filter
            if self.modified_after:
                mod_time = datetime.fromtimestamp(stat.st_mtime)
                if mod_time < self.modified_after:
                    return False
            if self.modified_before:
                mod_time = datetime.fromtimestamp(stat.st_mtime)
                if mod_time > self.modified_before:
                    return False
            
            return True
        except:
            return True  # If can't check, include it
    
    def run(self):
        try:
            self.setPriority(QThread.HighPriority)
            
            # Determine search directories
            search_dirs = self.directories
            if not search_dirs and self.use_smart_locations:
                search_dirs = [str(loc) for loc in get_smart_locations()]
            if not search_dirs:
                search_dirs = ['.']
            
            results = []
            
            # Search each directory with ripgrep
            for directory in search_dirs:
                cmd = [self.rg_path, '--files']
                
                if self.pattern:
                    cmd.extend(['--iglob', f'*{self.pattern}*'])
                
                cmd.append(directory)
                
                startupinfo = None
                creationflags = 0
                
                if IS_WINDOWS:
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    creationflags = subprocess.CREATE_NO_WINDOW
                
                result = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    encoding='utf-8', 
                    errors='ignore',
                    startupinfo=startupinfo,
                    creationflags=creationflags,
                    timeout=60
                )
                
                # Parse and filter results
                for filepath in result.stdout.split('\n'):
                    filepath = filepath.strip()
                    if filepath and self._apply_filters(filepath):
                        results.append({
                            'file': filepath,
                            'line_num': 0,
                            'line': f"📄 {os.path.basename(filepath)}",
                            'submatches': []
                        })
            
            self.finished.emit(results)
        except subprocess.TimeoutExpired:
            self.error.emit("Search timed out")
        except Exception as e:
            self.error.emit(str(e))

class ResultsHighlighter(QSyntaxHighlighter):
    """Syntax highlighter for search results"""
    
    def __init__(self, parent, pattern=""):
        super().__init__(parent)
        self.pattern = pattern
        self.highlight_format = QTextCharFormat()
        self.highlight_format.setBackground(QColor(255, 255, 0))
        self.highlight_format.setForeground(QColor(0, 0, 0))
    
    def highlightBlock(self, text):
        if not self.pattern:
            return
        
        # Simple case-insensitive highlighting
        pattern_lower = self.pattern.lower()
        text_lower = text.lower()
        
        index = text_lower.find(pattern_lower)
        while index >= 0:
            length = len(self.pattern)
            self.setFormat(index, length, self.highlight_format)
            index = text_lower.find(pattern_lower, index + length)

class SearchGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.searcher = AdvancedSearch()  # Use merged class instead of backend
        self.current_worker = None
        self.search_history = []
        self.current_results = []
        self.current_selected_file = None
        self.current_selected_line = None
        
        # Settings
        self.settings = QSettings('AdvancedSearch', 'SearchTool')
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        """Initialize the user interface"""
        self.setWindowTitle('🔍 Advanced Code Search')
        self.setGeometry(50, 50, 1600, 900)
        self.setMinimumSize(1200, 700)
        
        # Setup keyboard shortcuts
        self.setup_shortcuts()
        
        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(15, 15, 15, 15)
        
        # Top section - Search and Options
        top_section = QWidget()
        top_layout = QVBoxLayout(top_section)
        top_layout.setSpacing(8)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # Search input area
        search_group = self.create_search_group()
        top_layout.addWidget(search_group)
        
        # Options area (collapsible)
        options_group = self.create_options_group()
        top_layout.addWidget(options_group)
        
        main_layout.addWidget(top_section)
        
        # Splitter for results
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setChildrenCollapsible(False)  # Prevent collapsing panels
        
        # Results area (left side)
        results_widget = self.create_results_widget()
        splitter.addWidget(results_widget)
        
        # Preview area (right side)
        preview_widget = self.create_preview_widget()
        splitter.addWidget(preview_widget)
        
        # Set initial sizes and prevent resizing unless user drags
        splitter.setSizes([800, 800])
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        
        # Store splitter reference for later
        self.main_splitter = splitter
        
        main_layout.addWidget(splitter, 1)  # Stretch factor
        
        # Status bar
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMaximumHeight(18)
        self.statusBar.addPermanentWidget(self.progress_bar)
        
        # Apply modern theme
        self.apply_theme()
    
    def create_search_group(self):
        """Create search input group"""
        group = QGroupBox("🔍 Search")
        group.setObjectName("searchGroup")
        layout = QVBoxLayout()
        layout.setSpacing(12)
        
        # Main search bar with modern styling
        search_layout = QHBoxLayout()
        search_layout.setSpacing(8)
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔎 Enter search pattern (supports regex)...")
        self.search_input.returnPressed.connect(self.perform_search)
        self.search_input.setMinimumHeight(38)
        self.search_input.setObjectName("searchInput")
        search_layout.addWidget(self.search_input)
        
        self.search_button = QPushButton("🔍 Search")
        self.search_button.clicked.connect(self.perform_search)
        self.search_button.setMinimumSize(120, 38)
        self.search_button.setObjectName("searchButton")
        self.search_button.setCursor(Qt.PointingHandCursor)
        search_layout.addWidget(self.search_button)
        
        layout.addLayout(search_layout)
        
        # Path and mode in same row
        path_mode_layout = QHBoxLayout()
        path_mode_layout.setSpacing(10)
        
        # Path selection (left side)
        path_label = QLabel("📁 Path:")
        path_label.setMinimumWidth(50)
        path_mode_layout.addWidget(path_label)
        
        self.path_input = QLineEdit()
        self.path_input.setText(".")
        self.path_input.setMinimumHeight(32)
        path_mode_layout.addWidget(self.path_input, 2)
        
        browse_btn = QPushButton("📂 Browse")
        browse_btn.clicked.connect(self.browse_directory)
        browse_btn.setMinimumSize(90, 32)
        browse_btn.setCursor(Qt.PointingHandCursor)
        path_mode_layout.addWidget(browse_btn)
        
        # Search mode (right side)
        mode_label = QLabel("🎯 Mode:")
        mode_label.setMinimumWidth(55)
        path_mode_layout.addWidget(mode_label)
        
        self.search_mode = QComboBox()
        self.search_mode.addItems([
            "Basic Search",
            "Filename Search",
            "Find Definition",
            "Find Usages",
            "Find TODOs",
            "Multiple Patterns (AND)",
            "Multiple Patterns (OR)"
        ])
        self.search_mode.currentIndexChanged.connect(self.on_mode_changed)
        self.search_mode.setMinimumHeight(32)
        path_mode_layout.addWidget(self.search_mode, 1)
        
        # Language for definitions
        lang_label = QLabel("💻 Lang:")
        lang_label.setMinimumWidth(50)
        path_mode_layout.addWidget(lang_label)
        
        self.language_combo = QComboBox()
        self.language_combo.addItems([
            "Auto",
            "Python",
            "C#",
            "JavaScript",
            "TypeScript",
            "Go",
            "Rust",
            "Java",
            "C++",
            "C",
            "PHP",
            "Ruby",
            "Swift",
            "Kotlin"
        ])
        self.language_combo.setEnabled(False)
        self.language_combo.setMinimumHeight(32)
        path_mode_layout.addWidget(self.language_combo)
        
        layout.addLayout(path_mode_layout)
        
        group.setLayout(layout)
        return group
    
    def create_options_group(self):
        """Create options group"""
        group = QGroupBox("⚙️ Options")
        group.setObjectName("optionsGroup")
        layout = QHBoxLayout()
        layout.setSpacing(20)
        
        # File type filtering
        file_widget = QWidget()
        file_layout = QVBoxLayout(file_widget)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)
        
        file_label = QLabel("📄 File Types:")
        file_label.setStyleSheet("font-weight: bold; color: #4FC3F7;")
        file_layout.addWidget(file_label)
        
        self.file_types = QLineEdit()
        self.file_types.setPlaceholderText("e.g., cs, py, js")
        self.file_types.setMinimumHeight(28)
        file_layout.addWidget(self.file_types)
        
        layout.addWidget(file_widget)
        
        # Pattern options
        pattern_widget = QWidget()
        pattern_layout = QVBoxLayout(pattern_widget)
        pattern_layout.setContentsMargins(0, 0, 0, 0)
        pattern_layout.setSpacing(4)
        
        pattern_label = QLabel("🔤 Pattern Options:")
        pattern_label.setStyleSheet("font-weight: bold; color: #4FC3F7;")
        pattern_layout.addWidget(pattern_label)
        
        self.case_insensitive = QCheckBox("Case Insensitive")
        self.case_insensitive.setCursor(Qt.PointingHandCursor)
        pattern_layout.addWidget(self.case_insensitive)
        
        self.word_boundary = QCheckBox("Whole Words Only")
        self.word_boundary.setCursor(Qt.PointingHandCursor)
        pattern_layout.addWidget(self.word_boundary)
        
        self.fixed_string = QCheckBox("Fixed String")
        self.fixed_string.setCursor(Qt.PointingHandCursor)
        pattern_layout.addWidget(self.fixed_string)
        
        layout.addWidget(pattern_widget)
        
        # Context lines
        context_widget = QWidget()
        context_layout = QVBoxLayout(context_widget)
        context_layout.setContentsMargins(0, 0, 0, 0)
        context_layout.setSpacing(6)
        
        context_label = QLabel("📋 Context Lines:")
        context_label.setStyleSheet("font-weight: bold; color: #4FC3F7;")
        context_layout.addWidget(context_label)
        
        context_spin_layout = QHBoxLayout()
        context_spin_layout.setSpacing(8)
        
        before_label = QLabel("Before:")
        context_spin_layout.addWidget(before_label)
        
        self.context_before = QSpinBox()
        self.context_before.setMaximum(50)
        self.context_before.setMinimumWidth(60)
        self.context_before.setMinimumHeight(28)
        context_spin_layout.addWidget(self.context_before)
        
        after_label = QLabel("After:")
        context_spin_layout.addWidget(after_label)
        
        self.context_after = QSpinBox()
        self.context_after.setMaximum(50)
        self.context_after.setMinimumWidth(60)
        self.context_after.setMinimumHeight(28)
        context_spin_layout.addWidget(self.context_after)
        
        context_layout.addLayout(context_spin_layout)
        layout.addWidget(context_widget)
        
        # Advanced options
        advanced_widget = QWidget()
        advanced_layout = QVBoxLayout(advanced_widget)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(4)
        
        advanced_label = QLabel("🔧 Advanced:")
        advanced_label.setStyleSheet("font-weight: bold; color: #4FC3F7;")
        advanced_layout.addWidget(advanced_label)
        
        self.search_hidden = QCheckBox("Hidden Files")
        self.search_hidden.setCursor(Qt.PointingHandCursor)
        advanced_layout.addWidget(self.search_hidden)
        
        self.no_ignore = QCheckBox("Ignore .gitignore")
        self.no_ignore.setCursor(Qt.PointingHandCursor)
        advanced_layout.addWidget(self.no_ignore)
        
        layout.addWidget(advanced_widget)
        
        # Smart locations checkbox
        smart_widget = QWidget()
        smart_layout = QVBoxLayout(smart_widget)
        smart_layout.setContentsMargins(0, 0, 0, 0)
        smart_layout.setSpacing(4)
        
        smart_label = QLabel("📁 Search:")
        smart_label.setStyleSheet("font-weight: bold; color: #4FC3F7;")
        smart_layout.addWidget(smart_label)
        
        self.use_smart_locations = QCheckBox("Smart Locations")
        self.use_smart_locations.setChecked(True)
        self.use_smart_locations.setCursor(Qt.PointingHandCursor)
        self.use_smart_locations.setToolTip("Search Desktop, Documents, Downloads first")
        smart_layout.addWidget(self.use_smart_locations)
        
        layout.addWidget(smart_widget)
        layout.addStretch()
        
        group.setLayout(layout)
        return group
    
    def create_results_widget(self):
        """Create results display widget"""
        widget = QWidget()
        widget.setObjectName("resultsWidget")
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Results header with modern design
        header_widget = QWidget()
        header_widget.setObjectName("resultsHeader")
        header_widget.setStyleSheet("""
            #resultsHeader {
                background-color: #252525;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(12, 8, 12, 8)
        
        self.results_label = QLabel("📊 Results: 0 matches")
        self.results_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #4FC3F7;")
        header_layout.addWidget(self.results_label)
        
        header_layout.addStretch()
        
        # Action buttons with icons
        export_btn = QPushButton("💾 Export")
        export_btn.clicked.connect(self.export_results)
        export_btn.setMinimumSize(100, 32)
        export_btn.setCursor(Qt.PointingHandCursor)
        export_btn.setObjectName("actionButton")
        header_layout.addWidget(export_btn)
        
        clear_btn = QPushButton("🗑️ Clear")
        clear_btn.clicked.connect(self.clear_results)
        clear_btn.setMinimumSize(90, 32)
        clear_btn.setCursor(Qt.PointingHandCursor)
        clear_btn.setObjectName("actionButton")
        header_layout.addWidget(clear_btn)
        
        layout.addWidget(header_widget)
        
        # Tabs for different views with icons
        self.results_tabs = QTabWidget()
        self.results_tabs.setObjectName("resultsTabs")
        
        # List view - showing only file paths and line numbers
        self.results_list = QListWidget()
        self.results_list.itemClicked.connect(self.on_result_selected)
        self.results_list.setObjectName("resultsList")
        self.results_list.setAlternatingRowColors(True)
        self.results_tabs.addTab(self.results_list, "📋 Results")
        
        # Statistics view
        self.stats_text = QTextEdit()
        self.stats_text.setReadOnly(True)
        self.stats_text.setObjectName("statsText")
        self.results_tabs.addTab(self.stats_text, "📈 Statistics")
        
        layout.addWidget(self.results_tabs)
        
        return widget
    
    def create_preview_widget(self):
        """Create file preview widget"""
        widget = QWidget()
        widget.setObjectName("previewWidget")
        widget.setMinimumWidth(300)  # Prevent it from getting too small
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Preview header with modern design
        header_widget = QWidget()
        header_widget.setObjectName("previewHeader")
        header_widget.setStyleSheet("""
            #previewHeader {
                background-color: #252525;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(12, 8, 12, 8)
        
        self.preview_label = QLabel("👁️ Preview")
        self.preview_label.setStyleSheet("font-weight: bold; font-size: 15px; color: #81C784;")
        header_layout.addWidget(self.preview_label)
        
        header_layout.addStretch()
        
        # Action buttons
        open_btn = QPushButton("📂 Open")
        open_btn.clicked.connect(self.open_in_editor)
        open_btn.setMinimumSize(90, 32)
        open_btn.setCursor(Qt.PointingHandCursor)
        open_btn.setObjectName("actionButton")
        header_layout.addWidget(open_btn)
        
        copy_btn = QPushButton("📋 Copy Path")
        copy_btn.clicked.connect(self.copy_file_path)
        copy_btn.setMinimumSize(110, 32)
        copy_btn.setCursor(Qt.PointingHandCursor)
        copy_btn.setObjectName("actionButton")
        header_layout.addWidget(copy_btn)
        
        layout.addWidget(header_widget)
        
        # Preview text area with code styling
        self.preview_text = QTextEdit()
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont("Consolas", 10))
        self.preview_text.setObjectName("previewText")
        self.preview_text.setLineWrapMode(QTextEdit.NoWrap)
        self.preview_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.preview_text.setMinimumWidth(300)
        layout.addWidget(self.preview_text)
        
        return widget
    
    def apply_theme(self):
        """Apply modern dark theme with better organization"""
        self.setStyleSheet("""
            /* Main Window */
            QMainWindow {
                background-color: #1e1e1e;
            }
            
            /* Group Boxes */
            QGroupBox {
                background-color: #252526;
                border: 2px solid #3e3e42;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 16px;
                padding: 12px;
                font-weight: bold;
                font-size: 13px;
                color: #cccccc;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 12px;
                padding: 0 8px;
                background-color: #252526;
            }
            #searchGroup {
                border-color: #007acc;
            }
            #optionsGroup {
                border-color: #4FC3F7;
            }
            
            /* Line Edits */
            QLineEdit {
                background-color: #3c3c3c;
                border: 2px solid #3e3e42;
                border-radius: 4px;
                padding: 8px 12px;
                color: #cccccc;
                font-size: 13px;
                selection-background-color: #264f78;
            }
            QLineEdit:focus {
                border: 2px solid #007acc;
                background-color: #2d2d2d;
            }
            QLineEdit:hover {
                border: 2px solid #505050;
            }
            #searchInput {
                font-size: 14px;
                padding: 10px 14px;
            }
            
            /* Buttons */
            QPushButton {
                background-color: #0e639c;
                border: none;
                border-radius: 4px;
                padding: 8px 16px;
                color: white;
                font-weight: bold;
                font-size: 13px;
            }
            QPushButton:hover {
                background-color: #1177bb;
            }
            QPushButton:pressed {
                background-color: #005a9e;
            }
            QPushButton:disabled {
                background-color: #3e3e42;
                color: #808080;
            }
            #searchButton {
                background-color: #16825d;
                font-size: 14px;
            }
            #searchButton:hover {
                background-color: #1e9e6d;
            }
            #actionButton {
                background-color: #3e3e42;
                padding: 6px 12px;
            }
            #actionButton:hover {
                background-color: #505050;
            }
            
            /* Text Edits */
            QTextEdit, QListWidget, QTableWidget {
                background-color: #1e1e1e;
                border: 1px solid #3e3e42;
                border-radius: 4px;
                color: #cccccc;
                selection-background-color: #264f78;
                font-size: 12px;
            }
            #previewText {
                background-color: #1e1e1e;
                font-family: 'Consolas', 'Courier New', monospace;
                line-height: 1.4;
            }
            #statsText {
                background-color: #252526;
            }
            
            /* List Widget */
            #resultsList {
                background-color: #252526;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #3e3e42;
                color: #cccccc;
            }
            QListWidget::item:hover {
                background-color: #2a2d2e;
            }
            QListWidget::item:selected {
                background-color: #0e639c;
                color: white;
                border-left: 3px solid #007acc;
            }
            QListWidget::item:selected:hover {
                background-color: #1177bb;
            }
            QListWidget::item:alternate {
                background-color: #2a2a2a;
            }
            
            /* Table Widget */
            #resultsTable {
                background-color: #252526;
                gridline-color: #3e3e42;
            }
            QTableWidget::item {
                padding: 6px;
                border: none;
            }
            QTableWidget::item:selected {
                background-color: #094771;
                color: white;
            }
            QTableWidget::item:alternate {
                background-color: #2a2a2a;
            }
            QHeaderView::section {
                background-color: #323233;
                color: #cccccc;
                padding: 8px;
                border: none;
                border-right: 1px solid #3e3e42;
                border-bottom: 2px solid #007acc;
                font-weight: bold;
            }
            
            /* Combo Box */
            QComboBox {
                background-color: #3c3c3c;
                border: 2px solid #3e3e42;
                border-radius: 4px;
                padding: 6px 12px;
                color: #cccccc;
                font-size: 12px;
            }
            QComboBox:hover {
                border: 2px solid #505050;
            }
            QComboBox:focus {
                border: 2px solid #007acc;
            }
            QComboBox::drop-down {
                border: none;
                width: 20px;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 4px solid transparent;
                border-right: 4px solid transparent;
                border-top: 6px solid #cccccc;
                margin-right: 6px;
            }
            QComboBox QAbstractItemView {
                background-color: #252526;
                border: 1px solid #007acc;
                selection-background-color: #094771;
                color: #cccccc;
            }
            
            /* Check Box */
            QCheckBox {
                color: #cccccc;
                spacing: 8px;
                font-size: 12px;
            }
            QCheckBox::indicator {
                width: 18px;
                height: 18px;
                border: 2px solid #3e3e42;
                border-radius: 3px;
                background-color: #3c3c3c;
            }
            QCheckBox::indicator:hover {
                border: 2px solid #007acc;
            }
            QCheckBox::indicator:checked {
                background-color: #007acc;
                border: 2px solid #007acc;
            }
            
            /* Spin Box */
            QSpinBox {
                background-color: #3c3c3c;
                border: 2px solid #3e3e42;
                border-radius: 4px;
                padding: 4px 8px;
                color: #cccccc;
                font-size: 12px;
            }
            QSpinBox:hover {
                border: 2px solid #505050;
            }
            QSpinBox:focus {
                border: 2px solid #007acc;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: #3e3e42;
                border: none;
                width: 18px;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {
                background-color: #505050;
            }
            
            /* Tab Widget */
            #resultsTabs::pane {
                border: 1px solid #3e3e42;
                border-radius: 4px;
                background-color: #252526;
            }
            QTabBar::tab {
                background-color: #2d2d30;
                border: none;
                padding: 10px 20px;
                color: #969696;
                font-size: 12px;
                font-weight: bold;
                margin-right: 2px;
            }
            QTabBar::tab:hover {
                background-color: #3e3e42;
                color: #cccccc;
            }
            QTabBar::tab:selected {
                background-color: #007acc;
                color: white;
            }
            
            /* Status Bar */
            QStatusBar {
                background-color: #007acc;
                color: white;
                font-weight: bold;
                padding: 4px;
            }
            
            /* Progress Bar */
            QProgressBar {
                border: 1px solid #3e3e42;
                border-radius: 3px;
                background-color: #2d2d30;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #16825d;
                border-radius: 2px;
            }
            
            /* Labels */
            QLabel {
                color: #cccccc;
                font-size: 12px;
            }
            
            /* Scroll Bars */
            QScrollBar:vertical {
                background-color: #1e1e1e;
                width: 12px;
                border: none;
            }
            QScrollBar::handle:vertical {
                background-color: #424242;
                border-radius: 6px;
                min-height: 30px;
            }
            QScrollBar::handle:vertical:hover {
                background-color: #4e4e4e;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QScrollBar:horizontal {
                background-color: #1e1e1e;
                height: 12px;
                border: none;
            }
            QScrollBar::handle:horizontal {
                background-color: #424242;
                border-radius: 6px;
                min-width: 30px;
            }
            QScrollBar::handle:horizontal:hover {
                background-color: #4e4e4e;
            }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            
            /* Splitter */
            QSplitter::handle {
                background-color: #3e3e42;
                width: 3px;
            }
            QSplitter::handle:hover {
                background-color: #007acc;
            }
            QSplitter::handle:pressed {
                background-color: #1177bb;
            }
        """)
    
    def browse_directory(self):
        """Open directory browser"""
        directory = QFileDialog.getExistingDirectory(self, "Select Directory", self.path_input.text())
        if directory:
            self.path_input.setText(directory)
    
    def setup_shortcuts(self):
        """Setup keyboard shortcuts"""
        from PyQt5.QtWidgets import QShortcut
        from PyQt5.QtGui import QKeySequence
        
        # Ctrl+F - Focus search
        shortcut_search = QShortcut(QKeySequence("Ctrl+F"), self)
        shortcut_search.activated.connect(lambda: self.search_input.setFocus())
        
        # Ctrl+L - Focus path
        shortcut_path = QShortcut(QKeySequence("Ctrl+L"), self)
        shortcut_path.activated.connect(lambda: self.path_input.setFocus())
        
        # Ctrl+Return - Perform search
        shortcut_exec = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_exec.activated.connect(self.perform_search)
        
        # Ctrl+E - Export results
        shortcut_export = QShortcut(QKeySequence("Ctrl+E"), self)
        shortcut_export.activated.connect(self.export_results)
        
        # F5 - Repeat last search
        shortcut_refresh = QShortcut(QKeySequence("F5"), self)
        shortcut_refresh.activated.connect(self.perform_search)
    
    def on_mode_changed(self, index):
        """Handle search mode change"""
        mode = self.search_mode.currentText()
        
        # Enable/disable language combo for Find Definition
        self.language_combo.setEnabled("Definition" in mode)
        
        # Update placeholder based on mode
        if "Filename Search" in mode:
            self.search_input.setPlaceholderText("🔎 Enter filename pattern (e.g., admin)...")
            self.search_input.setEnabled(True)
        elif "Multiple Patterns" in mode:
            self.search_input.setPlaceholderText("Enter patterns separated by spaces...")
            self.search_input.setEnabled(True)
        elif "Definition" in mode:
            self.search_input.setPlaceholderText("Enter function/class name...")
            self.search_input.setEnabled(True)
        elif "Usages" in mode:
            self.search_input.setPlaceholderText("Enter symbol name...")
            self.search_input.setEnabled(True)
        elif "TODOs" in mode:
            self.search_input.setPlaceholderText("Will search for TODO and FIXME comments")
            self.search_input.setEnabled(False)
        else:  # Basic Search
            self.search_input.setPlaceholderText("🔎 Enter search pattern - searches inside files (supports regex)...")
            self.search_input.setEnabled(True)
    
    def perform_search(self):
        """Execute search based on current settings"""
        if self.current_worker and self.current_worker.isRunning():
            QMessageBox.warning(self, "Search Running", "A search is already in progress!")
            return
        
        # Get search parameters
        pattern = self.search_input.text().strip()
        path = self.path_input.text().strip() or "."
        mode = self.search_mode.currentText()
        
        # Validate
        if not pattern and "TODOs" not in mode:
            QMessageBox.warning(self, "No Pattern", "Please enter a search pattern!")
            return
        
        # Clear previous results
        self.clear_results()
        
        # Show progress
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate
        self.statusBar.showMessage("Searching...")
        self.search_button.setEnabled(False)
        
        # Build search kwargs
        kwargs = {
            'case_insensitive': self.case_insensitive.isChecked(),
            'word_boundary': self.word_boundary.isChecked(),
            'fixed_strings': self.fixed_string.isChecked(),
            'hidden': self.search_hidden.isChecked(),
            'no_ignore': self.no_ignore.isChecked(),
        }
        
        # Context
        if self.context_before.value() > 0:
            kwargs['before'] = self.context_before.value()
        if self.context_after.value() > 0:
            kwargs['after'] = self.context_after.value()
        
        # File types
        if self.file_types.text().strip():
            types = [t.strip() for t in self.file_types.text().split(',')]
            kwargs['type'] = types
        
        # Determine search function based on mode
        if "Filename Search" in mode:
            # Determine search directories
            directories = []
            if path and path != ".":
                directories = [path]
            
            use_smart_locations = self.use_smart_locations.isChecked()
            
            # Use ripgrep for filename search
            self.statusBar.showMessage("Searching with ripgrep...")
            self.current_worker = FilenameSearchWorker(
                pattern, directories, None, None,
                None, None, use_smart_locations
            )
            
            self.current_worker.finished.connect(self.on_search_finished)
            self.current_worker.error.connect(self.on_search_error)
            self.current_worker.start()
            
            # Add to history
            self.search_history.append({
                'pattern': pattern,
                'mode': mode,
                'path': path
            })
            return
        elif "Definition" in mode:
            lang = self.language_combo.currentText()
            if lang == "Auto":
                lang = None
            else:
                # Map display names to backend names
                lang_map = {
                    "Python": "python",
                    "C#": "csharp",
                    "JavaScript": "javascript",
                    "TypeScript": "typescript",
                    "Go": "go",
                    "Rust": "rust",
                    "Java": "java",
                    "C++": "cpp",
                    "C": "c",
                    "PHP": "php",
                    "Ruby": "ruby",
                    "Swift": "swift",
                    "Kotlin": "kotlin"
                }
                lang = lang_map.get(lang, lang.lower())
            search_func = self.searcher.find_definition
            args = (pattern, path, lang)
        elif "Usages" in mode:
            search_func = self.searcher.find_usages
            args = (pattern, path)
        elif "TODOs" in mode:
            search_func = self.searcher.find_todos
            args = (path,)
        elif "Multiple Patterns (AND)" in mode:
            patterns = pattern.split()
            search_func = self.searcher.search_multiple_patterns
            args = (patterns, path, "AND")
        elif "Multiple Patterns (OR)" in mode:
            patterns = pattern.split()
            search_func = self.searcher.search_multiple_patterns
            args = (patterns, path, "OR")
        else:  # Basic search
            search_func = self.searcher.search
            args = (pattern, path)
        
        # Create worker thread
        self.current_worker = SearchWorker(self.searcher, search_func, *args, **kwargs)
        self.current_worker.finished.connect(self.on_search_finished)
        self.current_worker.error.connect(self.on_search_error)
        self.current_worker.start()
        
        # Add to history
        self.search_history.append({
            'pattern': pattern,
            'mode': mode,
            'path': path
        })
    
    def on_search_finished(self, results):
        """Handle search completion"""
        self.current_results = results
        
        # Update UI
        self.progress_bar.setVisible(False)
        self.search_button.setEnabled(True)
        
        # Display results
        self.display_results(results)
        
        # Update status
        file_count = len(set(r['file'] for r in results))
        self.statusBar.showMessage(f"Found {len(results)} matches in {file_count} files")
        self.results_label.setText(f"Results: {len(results)} matches in {file_count} files")
    
    def on_search_error(self, error_msg):
        """Handle search error"""
        self.progress_bar.setVisible(False)
        self.search_button.setEnabled(True)
        self.statusBar.showMessage("Search failed")
        QMessageBox.critical(self, "Search Error", f"Search failed:\n{error_msg}")
    
    def display_results(self, results):
        """Display search results"""
        # List view - only show file:line format
        self.results_list.clear()
        for result in results[:1000]:  # Limit to 1000 for performance
            # Format: file.cs:123
            item_text = f"{result['file']}:{result['line_num']}"
            item = QListWidgetItem(item_text)
            item.setData(Qt.UserRole, result)
            # Ensure item is selectable
            item.setFlags(item.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            self.results_list.addItem(item)
        
        if len(results) > 1000:
            overflow_item = QListWidgetItem(f"... and {len(results) - 1000} more results")
            overflow_item.setFlags(overflow_item.flags() & ~Qt.ItemIsSelectable)  # Make it non-selectable
            self.results_list.addItem(overflow_item)
        
        # Statistics
        self.display_statistics(results)
    
    def display_statistics(self, results):
        """Display search statistics"""
        if not results:
            self.stats_text.setText("No results to analyze.")
            return
        
        from collections import defaultdict
        file_counts = defaultdict(int)
        for result in results:
            file_counts[result['file']] += 1
        
        stats_html = f"""
        <h2>📊 Search Statistics</h2>
        <p><b>Total Matches:</b> {len(results)}</p>
        <p><b>Files with Matches:</b> {len(file_counts)}</p>
        
        <h3>Top Files:</h3>
        <table border="1" cellpadding="5" style="border-collapse: collapse;">
        <tr><th>Count</th><th>File</th></tr>
        """
        
        for file, count in sorted(file_counts.items(), key=lambda x: x[1], reverse=True)[:20]:
            stats_html += f"<tr><td>{count}</td><td>{file}</td></tr>"
        
        stats_html += "</table>"
        
        self.stats_text.setHtml(stats_html)
    
    def on_result_selected(self, item):
        """Handle result selection from list"""
        result = item.data(Qt.UserRole)
        if result:
            self.show_preview(result)
            self.current_selected_file = result['file']
            self.current_selected_line = result['line_num']

    def show_preview(self, result):
        """Show file preview with context"""
        file_path = result['file']
        line_num = result['line_num']
        
        self.preview_label.setText(f"👁️ Preview: {file_path}:{line_num}")
        
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            # Show context around the match
            context_before = 5
            context_after = 5
            start = max(0, line_num - context_before - 1)
            end = min(len(lines), line_num + context_after)
            
            # Find minimum indentation to preserve structure but align left
            min_indent = float('inf')
            for i in range(start, end):
                line = lines[i].rstrip()
                if line.strip():  # Only consider non-empty lines
                    indent = len(line) - len(line.lstrip())
                    min_indent = min(min_indent, indent)
            
            if min_indent == float('inf'):
                min_indent = 0
            
            preview_text = ""
            for i in range(start, end):
                line = lines[i].rstrip()
                # Remove only the common minimum indentation
                if len(line) > min_indent:
                    adjusted_line = line[min_indent:]
                else:
                    adjusted_line = line.lstrip()
                    
                line_prefix = f"{i + 1:4d} | "
                
                if i + 1 == line_num:
                    preview_text += f"<b style='background-color: #264f78;'>{line_prefix}{adjusted_line}</b><br>"
                else:
                    preview_text += f"{line_prefix}{adjusted_line}<br>"
            
            self.preview_text.setHtml(f"<pre style='font-family: Consolas; margin: 0; padding: 8px;'>{preview_text}</pre>")
            
        except Exception as e:
            self.preview_text.setPlainText(f"Error loading preview: {e}")
    
    def clear_results(self):
        """Clear all results"""
        self.results_list.clear()
        self.stats_text.clear()
        self.preview_text.clear()
        self.current_results = []
        self.current_selected_file = None
        self.current_selected_line = None
        self.results_label.setText("📊 Results: 0 matches")
        self.preview_label.setText("👁️ Preview")
    
    
    def export_results(self):
        """Export results to file with better formatting"""
        if not self.current_results:
            QMessageBox.information(self, "No Results", "No results to export!")
            return
        
        file_path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Results", "", 
            "HTML Table (*.html);;JSON Files (*.json);;CSV Files (*.csv);;Text Files (*.txt);;Markdown Table (*.md)"
        )
        
        if not file_path:
            return
        
        try:
            if file_path.endswith('.html'):
                # HTML table export - beautiful visual table with syntax highlighting (DARK THEME)
                html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Search Results - {self.search_input.text()}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/csharp.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/javascript.min.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0d1117;
            padding: 20px;
            margin: 0;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            background: #161b22;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            overflow: hidden;
            border: 1px solid #30363d;
        }}
        .header {{
            background: linear-gradient(135deg, #1f6feb 0%, #8957e5 100%);
            color: white;
            padding: 30px;
            border-bottom: 2px solid #58a6ff;
        }}
        .header h1 {{
            margin: 0 0 20px 0;
            font-size: 32px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        .info {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .info-item {{
            background: rgba(255,255,255,0.15);
            padding: 10px 15px;
            border-radius: 5px;
            backdrop-filter: blur(10px);
        }}
        .info-label {{
            font-size: 12px;
            opacity: 0.9;
            margin-bottom: 5px;
            color: #c9d1d9;
        }}
        .info-value {{
            font-size: 18px;
            font-weight: bold;
            color: #ffffff;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 0;
        }}
        thead {{
            background: #0d1117;
            position: sticky;
            top: 0;
            z-index: 10;
            border-bottom: 2px solid #58a6ff;
        }}
        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #58a6ff;
            border-bottom: 2px solid #30363d;
        }}
        tbody tr {{
            border-bottom: 1px solid #21262d;
            transition: all 0.2s;
        }}
        tbody tr:hover {{
            background: #1c2128;
            transform: scale(1.001);
            box-shadow: 0 2px 8px rgba(88, 166, 255, 0.2);
        }}
        tbody tr:nth-child(even) {{
            background: #161b22;
        }}
        tbody tr:nth-child(even):hover {{
            background: #1c2128;
        }}
        td {{
            padding: 12px 15px;
            vertical-align: top;
            color: #c9d1d9;
        }}
        .file-cell {{
            color: #58a6ff;
            font-weight: 500;
            max-width: 450px;
            word-break: break-all;
            font-size: 13px;
        }}
        .line-cell {{
            color: #a371f7;
            font-weight: 700;
            text-align: center;
            width: 80px;
            font-size: 14px;
            background: #0d1117;
            border-radius: 4px;
        }}
        .content-cell {{
            font-family: 'Consolas', 'Courier New', monospace;
            max-width: 700px;
            overflow-x: auto;
        }}
        .content-cell pre {{
            margin: 0;
            padding: 0;
            background: transparent !important;
        }}
        .content-cell code {{
            padding: 8px 12px !important;
            border-radius: 4px;
            display: block;
            font-size: 13px;
            line-height: 1.5;
            background: #0d1117 !important;
            border: 1px solid #30363d;
        }}
        .hljs {{
            background: #0d1117 !important;
        }}
        .stats {{
            padding: 20px 30px;
            background: #0d1117;
            color: #c9d1d9;
            text-align: center;
            border-top: 2px solid #30363d;
        }}
        .match-highlight {{
            background: #ffd700;
            color: #000;
            padding: 2px 4px;
            border-radius: 2px;
            font-weight: bold;
        }}
        /* Scrollbar styling for dark theme */
        ::-webkit-scrollbar {{
            width: 12px;
            height: 12px;
        }}
        ::-webkit-scrollbar-track {{
            background: #0d1117;
        }}
        ::-webkit-scrollbar-thumb {{
            background: #30363d;
            border-radius: 6px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: #484f58;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Search Results</h1>
            <div class="info">
                <div class="info-item">
                    <div class="info-label">Pattern</div>
                    <div class="info-value">{self.search_input.text()}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Mode</div>
                    <div class="info-value">{self.search_mode.currentText()}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Total Matches</div>
                    <div class="info-value">{len(self.current_results)}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Files</div>
                    <div class="info-value">{len(set(r['file'] for r in self.current_results))}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Export Date</div>
                    <div class="info-value">{self._get_timestamp()}</div>
                </div>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>📁 File</th>
                    <th>📍 Line</th>
                    <th>📝 Content (Syntax Highlighted)</th>
                </tr>
            </thead>
            <tbody>
"""
                # Detect language from file extension
                def get_language(filename):
                    if filename.endswith('.cs'):
                        return 'csharp'
                    elif filename.endswith('.py'):
                        return 'python'
                    elif filename.endswith('.js'):
                        return 'javascript'
                    elif filename.endswith('.ts'):
                        return 'typescript'
                    elif filename.endswith('.java'):
                        return 'java'
                    elif filename.endswith('.cpp') or filename.endswith('.cc'):
                        return 'cpp'
                    elif filename.endswith('.go'):
                        return 'go'
                    elif filename.endswith('.rs'):
                        return 'rust'
                    elif filename.endswith('.php'):
                        return 'php'
                    elif filename.endswith('.rb'):
                        return 'ruby'
                    return 'plaintext'
                
                search_pattern = self.search_input.text().lower()
                
                for result in self.current_results:
                    file_name = result['file']
                    line_num = result['line_num']
                    content = result['line'].strip()
                    
                    # Escape HTML
                    content_escaped = content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('"', '&quot;')
                    
                    # Highlight the search pattern
                    if search_pattern:
                        import re
                        # Case-insensitive highlight
                        pattern = re.escape(search_pattern)
                        content_escaped = re.sub(f'({pattern})', r'<span class="match-highlight">\1</span>', 
                                                content_escaped, flags=re.IGNORECASE)
                    
                    lang = get_language(file_name)
                    
                    html += f"""                <tr>
                    <td class="file-cell">{file_name}</td>
                    <td class="line-cell">{line_num}</td>
                    <td class="content-cell"><pre><code class="language-{lang}">{content_escaped}</code></pre></td>
                </tr>
"""
                
                html += f"""            </tbody>
        </table>
        <div class="stats">
            ✨ Exported {len(self.current_results)} matches from {len(set(r['file'] for r in self.current_results))} files with syntax highlighting ✨
        </div>
    </div>
    <script>
        // Initialize syntax highlighting
        hljs.highlightAll();
        
        // Add copy button functionality (optional)
        document.querySelectorAll('code').forEach(block => {{
            block.style.cursor = 'pointer';
            block.title = 'Click to copy';
            block.addEventListener('click', function() {{
                navigator.clipboard.writeText(this.textContent);
                const original = this.style.background;
                this.style.background = '#4CAF50';
                setTimeout(() => this.style.background = original, 200);
            }});
        }});
    </script>
</body>
</html>"""
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(html)
                    
            elif file_path.endswith('.json'):
                # Standard structured JSON export
                export_data = {
                    "search_info": {
                        "total_matches": len(self.current_results),
                        "total_files": len(set(r['file'] for r in self.current_results)),
                        "export_date": self._get_timestamp(),
                        "search_pattern": self.search_input.text(),
                        "search_mode": self.search_mode.currentText(),
                        "search_path": self.path_input.text()
                    },
                    "results": []
                }
                
                # Group by file for better organization
                from collections import defaultdict
                by_file = defaultdict(list)
                for result in self.current_results:
                    by_file[result['file']].append({
                        "line_number": result['line_num'],
                        "content": result['line'].strip(),
                        "match_location": f"{result['file']}:{result['line_num']}"
                    })
                
                # Build structured results
                for file, matches in sorted(by_file.items()):
                    export_data["results"].append({
                        "file": file,
                        "match_count": len(matches),
                        "matches": matches
                    })
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(export_data, f, indent=2, ensure_ascii=False)
                    
            elif file_path.endswith('.csv'):
                # CSV export with proper quoting
                with open(file_path, 'w', encoding='utf-8', newline='') as f:
                    import csv
                    writer = csv.writer(f, quoting=csv.QUOTE_ALL)
                    writer.writerow(["File", "Line", "Content"])
                    for result in self.current_results:
                        writer.writerow([result['file'], result['line_num'], result['line'].strip()])
                        
            elif file_path.endswith('.md'):
                # Markdown table export using tabulate
                try:
                    from tabulate import tabulate
                    
                    # Prepare table data
                    table_data = []
                    for result in self.current_results:
                        table_data.append([
                            result['file'],
                            result['line_num'],
                            result['line'].strip()[:80]  # Truncate long lines
                        ])
                    
                    # Create markdown table
                    markdown = f"# Search Results\n\n"
                    markdown += f"**Pattern:** `{self.search_input.text()}`\n"
                    markdown += f"**Mode:** {self.search_mode.currentText()}\n"
                    markdown += f"**Path:** `{self.path_input.text()}`\n"
                    markdown += f"**Total Matches:** {len(self.current_results)}\n"
                    markdown += f"**Files:** {len(set(r['file'] for r in self.current_results))}\n"
                    markdown += f"**Date:** {self._get_timestamp()}\n\n"
                    markdown += "---\n\n"
                    markdown += "## Results\n\n"
                    markdown += tabulate(table_data, headers=["File", "Line", "Content"], tablefmt="github")
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(markdown)
                        
                except ImportError:
                    # Fallback if tabulate not installed
                    QMessageBox.warning(
                        self, "Missing Module", 
                        "Markdown export requires 'tabulate' module.\n"
                        "Install with: pip install tabulate\n\n"
                        "Falling back to simple markdown format..."
                    )
                    
                    # Simple markdown without tabulate
                    markdown = f"# Search Results\n\n"
                    markdown += f"**Pattern:** `{self.search_input.text()}`\n"
                    markdown += f"**Total Matches:** {len(self.current_results)}\n\n"
                    markdown += "## Matches\n\n"
                    
                    from collections import defaultdict
                    by_file = defaultdict(list)
                    for result in self.current_results:
                        by_file[result['file']].append(result)
                    
                    for file, matches in sorted(by_file.items()):
                        markdown += f"### {file}\n\n"
                        for match in matches:
                            markdown += f"- **Line {match['line_num']}:** `{match['line'].strip()}`\n"
                        markdown += "\n"
                    
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(markdown)
                        
            else:  # .txt
                # Clean text export
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(f"Search Results\n")
                    f.write(f"{'=' * 70}\n\n")
                    f.write(f"Pattern: {self.search_input.text()}\n")
                    f.write(f"Mode: {self.search_mode.currentText()}\n")
                    f.write(f"Path: {self.path_input.text()}\n")
                    f.write(f"Total Matches: {len(self.current_results)}\n")
                    f.write(f"Files: {len(set(r['file'] for r in self.current_results))}\n")
                    f.write(f"Date: {self._get_timestamp()}\n")
                    f.write(f"\n{'-' * 70}\n\n")
                    
                    from collections import defaultdict
                    by_file = defaultdict(list)
                    for result in self.current_results:
                        by_file[result['file']].append(result)
                    
                    for file, matches in sorted(by_file.items()):
                        f.write(f"\n{file}\n")
                        f.write(f"{'-' * len(file)}\n")
                        for match in matches:
                            f.write(f"  Line {match['line_num']:4d}: {match['line'].rstrip()}\n")
                        f.write("\n")
            
            QMessageBox.information(self, "Success", f"Results exported to:\n{file_path}")
            
        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export:\n{e}")
    
    def _get_timestamp(self):
        """Get current timestamp for exports"""
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    def open_in_editor(self):
        """Open current file in default editor"""
        if not self.current_selected_file:
            QMessageBox.warning(self, "No File Selected", "Please select a result first!")
            return
        
        file_path = self.current_selected_file
        
        try:
            if sys.platform == 'win32':
                os.startfile(file_path)
            elif sys.platform == 'darwin':
                subprocess.run(['open', file_path])
            else:
                subprocess.run(['xdg-open', file_path])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to open file:\n{e}")
    
    def copy_file_path(self):
        """Copy file path to clipboard"""
        if not self.current_selected_file:
            QMessageBox.warning(self, "No File Selected", "Please select a result first!")
            return
        
        file_path = self.current_selected_file
        QApplication.clipboard().setText(file_path)
        self.statusBar.showMessage(f"Copied: {file_path}", 3000)
    
    def load_settings(self):
        """Load saved settings"""
        self.path_input.setText(self.settings.value('last_path', '.'))
        self.case_insensitive.setChecked(self.settings.value('case_insensitive', True, type=bool))  # Default to True
        self.word_boundary.setChecked(self.settings.value('word_boundary', False, type=bool))
        self.search_hidden.setChecked(self.settings.value('search_hidden', False, type=bool))
        
        # Show tool availability status
        self.statusBar.showMessage("Tools: ripgrep ✅ | Ready to search!")
    
    def save_settings(self):
        """Save current settings"""
        self.settings.setValue('last_path', self.path_input.text())
        self.settings.setValue('case_insensitive', self.case_insensitive.isChecked())
        self.settings.setValue('word_boundary', self.word_boundary.isChecked())
        self.settings.setValue('search_hidden', self.search_hidden.isChecked())
    
    def closeEvent(self, event):
        """Handle window close"""
        self.save_settings()
        event.accept()

def main_gui():
    """Launch GUI mode"""
    app = QApplication(sys.argv)
    app.setStyle('Fusion')  # Modern style
    
    window = SearchGUI()
    window.show()
    
    sys.exit(app.exec_())

def generate_html_export(results, pattern, mode, path):
    """Generate HTML export for CLI mode"""
    import html
    from datetime import datetime
    
    # Detect language from file extension for syntax highlighting
    def detect_language(filename):
        ext_map = {
            '.py': 'python', '.js': 'javascript', '.ts': 'typescript',
            '.cs': 'csharp', '.java': 'java', '.cpp': 'cpp', '.c': 'c',
            '.go': 'go', '.rs': 'rust', '.php': 'php', '.rb': 'ruby',
            '.swift': 'swift', '.kt': 'kotlin', '.html': 'html',
            '.css': 'css', '.json': 'json', '.xml': 'xml'
        }
        import os
        _, ext = os.path.splitext(filename)
        return ext_map.get(ext.lower(), 'plaintext')
    
    # Count unique files
    unique_files = len(set(r['file'] for r in results))
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Search Results - {html.escape(pattern or 'N/A')}</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/csharp.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/javascript.min.js"></script>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #0d1117;
            padding: 20px;
            margin: 0;
        }}
        .container {{
            max-width: 1600px;
            margin: 0 auto;
            background: #161b22;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.5);
            overflow: hidden;
            border: 1px solid #30363d;
        }}
        .header {{
            background: linear-gradient(135deg, #1f6feb 0%, #8957e5 100%);
            color: white;
            padding: 30px;
            border-bottom: 2px solid #58a6ff;
        }}
        .header h1 {{
            margin: 0 0 20px 0;
            font-size: 32px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        .info {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-top: 20px;
        }}
        .info-item {{
            background: rgba(255,255,255,0.15);
            padding: 10px 15px;
            border-radius: 5px;
            backdrop-filter: blur(10px);
        }}
        .info-label {{
            font-size: 12px;
            opacity: 0.9;
            margin-bottom: 5px;
            color: #c9d1d9;
        }}
        .info-value {{
            font-size: 18px;
            font-weight: bold;
            color: #ffffff;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 0;
        }}
        thead {{
            background: #0d1117;
            position: sticky;
            top: 0;
            z-index: 10;
            border-bottom: 2px solid #58a6ff;
        }}
        th {{
            padding: 15px;
            text-align: left;
            font-weight: 600;
            color: #58a6ff;
            border-bottom: 2px solid #30363d;
        }}
        tbody tr {{
            border-bottom: 1px solid #21262d;
            transition: all 0.2s;
        }}
        tbody tr:hover {{
            background: #1c2128;
            transform: scale(1.001);
            box-shadow: 0 2px 8px rgba(88, 166, 255, 0.2);
        }}
        tbody tr:nth-child(even) {{
            background: #161b22;
        }}
        tbody tr:nth-child(even):hover {{
            background: #1c2128;
        }}
        td {{
            padding: 12px 15px;
            vertical-align: top;
            color: #c9d1d9;
        }}
        .file-cell {{
            color: #58a6ff;
            font-weight: 500;
            max-width: 450px;
            word-break: break-all;
            font-size: 13px;
        }}
        .line-cell {{
            color: #a371f7;
            font-weight: 700;
            text-align: center;
            width: 80px;
            font-size: 14px;
            background: #0d1117;
            border-radius: 4px;
        }}
        .content-cell {{
            font-family: 'Consolas', 'Courier New', monospace;
            max-width: 700px;
            overflow-x: auto;
        }}
        .content-cell pre {{
            margin: 0;
            padding: 0;
            background: transparent !important;
        }}
        .content-cell code {{
            padding: 8px 12px !important;
            border-radius: 4px;
            display: block;
            font-size: 13px;
            line-height: 1.5;
            background: #0d1117 !important;
            border: 1px solid #30363d;
        }}
        .hljs {{
            background: #0d1117 !important;
        }}
        .stats {{
            padding: 20px 30px;
            background: #0d1117;
            color: #c9d1d9;
            text-align: center;
            border-top: 2px solid #30363d;
        }}
        .match-highlight {{
            background: #ffd700;
            color: #000;
            padding: 2px 4px;
            border-radius: 2px;
            font-weight: bold;
        }}
        ::-webkit-scrollbar {{
            width: 12px;
            height: 12px;
        }}
        ::-webkit-scrollbar-track {{
            background: #0d1117;
        }}
        ::-webkit-scrollbar-thumb {{
            background: #30363d;
            border-radius: 6px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: #484f58;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🔍 Search Results</h1>
            <div class="info">
                <div class="info-item">
                    <div class="info-label">Pattern</div>
                    <div class="info-value">{html.escape(pattern or 'N/A')}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Mode</div>
                    <div class="info-value">{html.escape(mode)}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Total Matches</div>
                    <div class="info-value">{len(results)}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Files</div>
                    <div class="info-value">{unique_files}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">Export Date</div>
                    <div class="info-value">{timestamp}</div>
                </div>
            </div>
        </div>
        <table>
            <thead>
                <tr>
                    <th>📁 File</th>
                    <th>📍 Line</th>
                    <th>💬 Content</th>
                </tr>
            </thead>
            <tbody>
"""
    
    # Add table rows
    for result in results:
        file_path = html.escape(result['file'])
        line_num = result['line_num'] if result['line_num'] > 0 else '-'
        content = html.escape(result['line'])
        
        # Detect language for syntax highlighting
        lang = detect_language(result['file'])
        
        html_content += f"""                <tr>
                    <td class="file-cell">{file_path}</td>
                    <td class="line-cell">{line_num}</td>
                    <td class="content-cell"><pre><code class="language-{lang}">{content}</code></pre></td>
                </tr>
"""
    
    html_content += """            </tbody>
        </table>
        <div class="stats">
            <p>Generated by Advanced Search Tool - CLI Mode</p>
        </div>
    </div>
    <script>
        hljs.highlightAll();
    </script>
</body>
</html>"""
    
    return html_content

def main_cli(args):
    """Run CLI mode"""
    import json
    from datetime import datetime
    
    # Create search instance
    searcher = AdvancedSearch()
    
    # Perform search based on mode
    results = []
    
    if args.mode == 'content':
        results = searcher.search(
            args.pattern,
            args.path,
            case_insensitive=args.ignore_case,
            whole_word=args.whole_word,
            file_type=args.type,
            context_lines=args.context
        )
    elif args.mode == 'filename':
        from concurrent.futures import ThreadPoolExecutor
        worker = FilenameSearchWorker(
            args.pattern,
            [args.path] if args.path != '.' else [],
            None, None, None, None,
            use_smart_locations=args.smart_locations
        )
        # Run synchronously in CLI mode
        worker.run()
        # Can't get signal results easily, so use direct ripgrep call
        import subprocess
        cmd = ['rg', '--files']
        if args.pattern:
            cmd.extend(['--iglob', f'*{args.pattern}*'])
        cmd.append(args.path)
        
        startupinfo = None
        creationflags = 0
        if IS_WINDOWS:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            creationflags = subprocess.CREATE_NO_WINDOW
        
        result = subprocess.run(cmd, capture_output=True, text=True,
                               startupinfo=startupinfo, creationflags=creationflags)
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line:
                results.append({'file': line, 'line_num': 0, 'line': line})
    
    elif args.mode == 'definition':
        results = searcher.find_definition(args.pattern, args.path, args.language)
    elif args.mode == 'usages':
        results = searcher.find_usages(args.pattern, args.path)
    elif args.mode == 'todos':
        results = searcher.find_todos(args.path)
    
    # Output results
    if args.output == 'html':
        # Generate HTML output with proper encoding
        html_content = generate_html_export(results, args.pattern, args.mode, args.path)
        # Write to stdout with UTF-8 encoding
        import sys
        sys.stdout.reconfigure(encoding='utf-8')
        print(html_content)
    elif args.output == 'json':
        print(json.dumps(results, indent=2))
    elif args.output == 'simple':
        for result in results:
            if result['line_num'] > 0:
                print(f"{result['file']}:{result['line_num']}: {result['line']}")
            else:
                print(result['file'])
    else:  # detailed
        for i, result in enumerate(results, 1):
            print(f"\n--- Result {i} ---")
            print(f"File: {result['file']}")
            if result['line_num'] > 0:
                print(f"Line: {result['line_num']}")
                print(f"Content: {result['line']}")
    
    # Print summary (to stderr so it doesn't interfere with output)
    if args.output != 'html':
        print(f"\n✅ Found {len(results)} results", file=sys.stderr)
    return 0 if results else 1

def main():
    """Main entry point - detect CLI or GUI mode"""
    import argparse
    import sys
    import os
    
    # Check if any arguments provided (besides script name)
    if len(sys.argv) > 1:
        # Check for --help or -h first - show GUI help dialog if no console
        if '--help' in sys.argv or '-h' in sys.argv:
            # Try to detect if we have a console
            try:
                # Try writing to stdout
                sys.stdout.write('')
                sys.stdout.flush()
                has_console = True
            except:
                has_console = False
            
            if not has_console:
                # Show help in GUI dialog if no console
                from PyQt5.QtWidgets import QApplication, QMessageBox, QTextEdit, QDialog, QVBoxLayout, QPushButton
                app = QApplication(sys.argv)
                
                help_text = """🔍 Advanced Code Search - CLI/GUI Tool

USAGE:
    search.exe [pattern] [path] [options]
    search.exe                    # Launch GUI mode
    search.exe --gui              # Force GUI mode

SEARCH MODES:
    -m content        Search inside file contents (default)
    -m filename       Search by filename
    -m definition     Find symbol definitions
    -m usages         Find symbol usages
    -m todos          Find TODO/FIXME comments

OPTIONS:
    -i, --ignore-case           Case-insensitive search
    -w, --whole-word            Match whole words only
    -t, --type TYPE             File type filter (cs, py, js, etc.)
    -C, --context NUM           Context lines
    -l, --language LANG         Language for definition search
    -s, --smart-locations       Search Desktop, Documents, etc.

OUTPUT FORMATS:
    -o simple                   file:line: content (default)
    -o detailed                 Detailed format with headers
    -o json                     JSON format
    -o html                     Beautiful HTML table with syntax highlighting

EXAMPLES:
    search.exe "admin" -i
    search.exe "class.*Admin" -t cs
    search.exe "admin" -m filename
    search.exe -m todos
    search.exe "admin" -o html > results.html

NOTE: For CLI mode, you must run this from a terminal/console.
TIP: Run without arguments to open the GUI!
"""
                
                dialog = QDialog()
                dialog.setWindowTitle("Advanced Search - Help")
                dialog.resize(700, 600)
                layout = QVBoxLayout()
                
                text_edit = QTextEdit()
                text_edit.setPlainText(help_text)
                text_edit.setReadOnly(True)
                text_edit.setStyleSheet("""
                    QTextEdit {
                        background-color: #1e1e1e;
                        color: #cccccc;
                        font-family: 'Consolas', 'Courier New', monospace;
                        font-size: 12px;
                        padding: 10px;
                    }
                """)
                layout.addWidget(text_edit)
                
                close_btn = QPushButton("Close")
                close_btn.clicked.connect(dialog.accept)
                close_btn.setStyleSheet("""
                    QPushButton {
                        background-color: #0e639c;
                        color: white;
                        padding: 8px 16px;
                        border-radius: 4px;
                        font-weight: bold;
                    }
                    QPushButton:hover {
                        background-color: #1177bb;
                    }
                """)
                layout.addWidget(close_btn)
                
                dialog.setLayout(layout)
                dialog.setStyleSheet("QDialog { background-color: #1e1e1e; }")
                dialog.exec_()
                return 0
        
        # Check if console is available for CLI operations
        try:
            sys.stdout.write('')
            sys.stdout.flush()
            has_console = True
        except:
            has_console = False
        
        if not has_console and '--gui' not in sys.argv:
            # No console but CLI mode requested - show error and launch GUI
            from PyQt5.QtWidgets import QApplication, QMessageBox
            app = QApplication(sys.argv)
            QMessageBox.warning(
                None, 
                "No Console Available",
                "⚠️ CLI mode requires a console/terminal.\n\n"
                "To use CLI mode:\n"
                "1. Open Command Prompt or PowerShell\n"
                "2. Run: search.exe [arguments]\n\n"
                "Or build with 'Console Based' option in auto-py-to-exe.\n\n"
                "Launching GUI mode instead..."
            )
            main_gui()
            return 0
        
        # CLI mode
        parser = argparse.ArgumentParser(
            description='🔍 Advanced Code Search - CLI/GUI Tool',
            epilog='Run without arguments to launch GUI mode'
        )
        
        # Main arguments
        parser.add_argument('pattern', nargs='?', help='Search pattern')
        parser.add_argument('path', nargs='?', default='.', help='Path to search (default: current directory)')
        
        # Mode selection
        parser.add_argument('-m', '--mode', choices=['content', 'filename', 'definition', 'usages', 'todos'],
                          default='content', help='Search mode (default: content)')
        
        # Options
        parser.add_argument('-i', '--ignore-case', action='store_true', help='Case-insensitive search')
        parser.add_argument('-w', '--whole-word', action='store_true', help='Match whole words only')
        parser.add_argument('-t', '--type', help='File type filter (e.g., py, js, cs)')
        parser.add_argument('-C', '--context', type=int, default=0, help='Context lines (default: 0)')
        parser.add_argument('-l', '--language', help='Language for definition search (auto-detect if not specified)')
        parser.add_argument('-s', '--smart-locations', action='store_true', help='Search in smart locations (Desktop, Documents, etc.)')
        
        # Output format
        parser.add_argument('-o', '--output', choices=['simple', 'detailed', 'json', 'html'],
                          default='simple', help='Output format (default: simple)')
        
        # GUI flag
        parser.add_argument('--gui', action='store_true', help='Force GUI mode')
        
        args = parser.parse_args()
        
        # Force GUI if --gui flag
        if args.gui:
            main_gui()
        elif not args.pattern and args.mode != 'todos':
            # No pattern provided and not todos mode - show help
            parser.print_help()
            print("\n💡 Tip: Run without arguments to launch GUI mode")
            return 1
        else:
            # CLI mode
            return main_cli(args)
    else:
        # No arguments - launch GUI
        main_gui()

if __name__ == '__main__':
    sys.exit(main() or 0)
