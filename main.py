import sys
import os
import subprocess
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QPushButton, QSplitter, QFileDialog, QDockWidget, 
                               QTreeView, QFileSystemModel, QMenu, QPlainTextEdit, 
                               QLineEdit, QToolBar, QMessageBox, QLabel)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QAction, QFont
from PySide6.QtCore import Qt, QDir

class NexusStudioUltimate(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Code_Analyzer")
        self.resize(1600, 950)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; color: #cccccc; }
            QDockWidget { font-weight: bold; color: #cccccc; }
            QDockWidget::title { background: #252526; padding: 6px; }
            QTreeView, QPlainTextEdit, QLineEdit { 
                background: #1e1e1e; color: #d4d4d4; border: 1px solid #333; font-family: Consolas;
            }
            QToolBar { background: #2d2d30; border: none; padding: 4px; }
            QPushButton { background: #333333; color: white; border-radius: 3px; padding: 6px 12px; margin: 2px;}
            QPushButton:hover { background: #404040; }
            QPushButton#ActionBtn { background: #0e639c; font-weight: bold; }
            QPushButton#ActionBtn:hover { background: #1177bb; }
            QPushButton#RunBtn { background: #28a745; font-weight: bold; }
            QPushButton#RunBtn:hover { background: #218838; }
        """)

        self.current_file = None
        self.compare_file = None
        self.is_diff_mode = False
        
        self.setup_ui()
        
    def setup_ui(self):
        # --- 1. TOOLBAR ---
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        
        self.toolbar.addWidget(QLabel(" 🐍 Venv: "))
        self.venv_input = QLineEdit()
        self.venv_input.setPlaceholderText("Path to python.exe (leave empty for system default)")
        self.venv_input.setFixedWidth(250)
        self.toolbar.addWidget(self.venv_input)
        
        run_btn = QPushButton("▶ Run")
        run_btn.setObjectName("RunBtn")
        run_btn.clicked.connect(self.execute_code)
        self.toolbar.addWidget(run_btn)
        
        save_btn = QPushButton("💾 Save")
        save_btn.setObjectName("ActionBtn")
        save_btn.clicked.connect(self.save_current_file)
        self.toolbar.addWidget(save_btn)

        self.toolbar.addSeparator()
        self.toolbar.addWidget(QLabel("  |  Mode: "))

        self.edit_mode_btn = QPushButton("📝 Edit Mode")
        self.edit_mode_btn.clicked.connect(self.enable_edit_mode)
        self.toolbar.addWidget(self.edit_mode_btn)

        self.compare_mode_btn = QPushButton("🔍 Compare Mode")
        self.compare_mode_btn.clicked.connect(self.enable_compare_mode)
        self.toolbar.addWidget(self.compare_mode_btn)

        # --- 2. FILE EXPLORER (LEFT) ---
        self.explorer_dock = QDockWidget("Project Explorer", self)
        self.file_model = QFileSystemModel()
        self.file_model.setRootPath(QDir.currentPath())
        
        self.tree_view = QTreeView()
        self.tree_view.setModel(self.file_model)
        self.tree_view.setRootIndex(self.file_model.index(QDir.currentPath()))
        self.tree_view.setColumnWidth(0, 220)
        for i in range(1, 4): self.tree_view.hideColumn(i) 
        
        self.tree_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_view.customContextMenuRequested.connect(self.show_file_menu)
        self.tree_view.doubleClicked.connect(self.load_file_from_tree)
        
        self.explorer_dock.setWidget(self.tree_view)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.explorer_dock)

        # --- 3. TERMINAL (BOTTOM) ---
        self.terminal_dock = QDockWidget("Terminal Output", self)
        self.terminal = QPlainTextEdit()
        self.terminal.setReadOnly(True)
        self.terminal_dock.setWidget(self.terminal)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.terminal_dock)

        # --- 4. MONACO ENGINE (CENTER) ---
        self.browser = QWebEngineView()
        self.setCentralWidget(self.browser)
        self.init_monaco()

    # --- THE DYNAMIC MONACO ENGINE ---
    def init_monaco(self):
        """Loads Monaco with the ability to destroy and recreate itself as a Diff or Standard Editor."""
        html = """
        <!DOCTYPE html><html><head>
            <style>body, html { margin: 0; height: 100%; overflow: hidden; background-color: #1e1e1e; } #container { height: 100%; }</style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs/loader.min.js"></script>
        </head><body>
            <div id="container"></div>
            <script>
                var currentEditor = null;
                var container = document.getElementById('container');
                
                require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs' } });
                require(['vs/editor/editor.main'], function() {
                    window.openStandardEditor('# Welcome to Nexus Ultimate\\n# Double click a file to start editing.\\n');
                });

                function disposeCurrent() {
                    if (currentEditor) { currentEditor.dispose(); currentEditor = null; }
                    container.innerHTML = '';
                }

                // Call this from Python to open Single Edit Mode
                window.openStandardEditor = function(code) {
                    disposeCurrent();
                    currentEditor = monaco.editor.create(container, {
                        value: code, language: 'python', theme: 'vs-dark', automaticLayout: true, fontSize: 14
                    });
                };

                // Call this from Python to open Dual Compare Mode
                window.openDiffEditor = function(oldCode, newCode) {
                    disposeCurrent();
                    currentEditor = monaco.editor.createDiffEditor(container, {
                        theme: 'vs-dark', renderSideBySide: true, automaticLayout: true, fontSize: 14, readOnly: true
                    });
                    currentEditor.setModel({
                        original: monaco.editor.createModel(oldCode, 'python'),
                        modified: monaco.editor.createModel(newCode, 'python')
                    });
                };

                // Gets code from Standard Editor for saving
                window.getEditorValue = function() {
                    if (currentEditor && currentEditor.getValue) { return currentEditor.getValue(); }
                    return "";
                };
            </script>
        </body></html>
        """
        self.browser.setHtml(html)

    # --- MODE SWITCHING & COMPARING ---
    def enable_edit_mode(self):
        """Switches Monaco to single-pane text editor."""
        self.is_diff_mode = False
        self.edit_mode_btn.setStyleSheet("background: #0e639c;") # Highlight active
        self.compare_mode_btn.setStyleSheet("")
        
        if self.current_file and os.path.exists(self.current_file):
            with open(self.current_file, 'r', encoding='utf-8') as f:
                code = f.read()
        else:
            code = "# Select a file to edit"
            
        safe_code = json.dumps(code)
        self.browser.page().runJavaScript(f"if (window.openStandardEditor) window.openStandardEditor({safe_code});")
        self.terminal.appendPlainText("> Switched to Edit Mode")

    def enable_compare_mode(self):
        """Asks for a file to compare against, then switches Monaco to dual-pane Diff view."""
        if not self.current_file:
            QMessageBox.warning(self, "Compare", "Please open a main file first (Double click in Explorer).")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Select Older/Original File to Compare", "", "Python Files (*.py);;All Files (*)")
        if not file_path: return

        self.compare_file = file_path
        self.is_diff_mode = True
        self.compare_mode_btn.setStyleSheet("background: #0e639c;") # Highlight active
        self.edit_mode_btn.setStyleSheet("")

        # Read both files
        with open(self.compare_file, 'r', encoding='utf-8') as f:
            old_code = f.read()
        with open(self.current_file, 'r', encoding='utf-8') as f:
            new_code = f.read()

        safe_old = json.dumps(old_code)
        safe_new = json.dumps(new_code)
        
        self.browser.page().runJavaScript(f"if (window.openDiffEditor) window.openDiffEditor({safe_old}, {safe_new});")
        self.terminal.appendPlainText(f"> Comparing: {os.path.basename(self.compare_file)} (Left) vs {os.path.basename(self.current_file)} (Right)")

    # --- FILE & EXECUTION LOGIC ---
    def show_file_menu(self, position):
        indexes = self.tree_view.selectedIndexes()
        if not indexes: return
        index = indexes[0]
        file_path = self.file_model.filePath(index)
        if not self.file_model.isDir(index):
            file_path = os.path.dirname(file_path)

        menu = QMenu()
        new_file_act = menu.addAction("📄 New Python File")
        action = menu.exec(self.tree_view.viewport().mapToGlobal(position))
        
        if action == new_file_act:
            new_path = os.path.join(file_path, "new_script.py")
            with open(new_path, 'w') as f: f.write("# Start coding here\n")
            self.terminal.appendPlainText(f"> Created {new_path}")

    def load_file_from_tree(self, index):
        file_path = self.file_model.filePath(index)
        if os.path.isfile(file_path):
            self.current_file = file_path
            self.setWindowTitle(f"Nexus Studio Ultimate - {os.path.basename(file_path)}")
            self.enable_edit_mode() # Always open files in edit mode first

    def save_current_file(self):
        if not self.current_file or self.is_diff_mode:
            QMessageBox.warning(self, "Warning", "Cannot save while in Diff mode or no file is open.")
            return
        self.browser.page().runJavaScript("window.getEditorValue()", self._write_to_file)

    def _write_to_file(self, code_content):
        try:
            with open(self.current_file, 'w', encoding='utf-8') as f:
                f.write(code_content)
            self.terminal.appendPlainText(f"> Saved successfully: {os.path.basename(self.current_file)}")
        except Exception as e:
            self.terminal.appendPlainText(f"> Save Error: {str(e)}")

    def execute_code(self):
        if not self.current_file: return
        if not self.is_diff_mode:
            self.browser.page().runJavaScript("window.getEditorValue()", self._run_after_save)
        else:
            self.terminal.appendPlainText("> Exit Compare mode to run code.")

    def _run_after_save(self, code_content):
        with open(self.current_file, 'w', encoding='utf-8') as f:
            f.write(code_content)

        python_exe = self.venv_input.text().strip() or sys.executable
        self.terminal.appendPlainText(f"\n--- Running: {os.path.basename(self.current_file)} ---")
        
        try:
            process = subprocess.Popen([python_exe, self.current_file], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=os.path.dirname(self.current_file))
            stdout, stderr = process.communicate()
            if stdout: self.terminal.appendPlainText(stdout)
            if stderr: self.terminal.appendPlainText(f"ERROR:\n{stderr}")
        except Exception as e:
            self.terminal.appendPlainText(f"Failed to execute. Error: {str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    window = NexusStudioUltimate()
    window.show()
    sys.exit(app.exec())
