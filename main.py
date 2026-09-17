import sys
import os
import subprocess
import json
import ast
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QPushButton, QSplitter, QFileDialog, QDockWidget, 
                               QTreeView, QFileSystemModel, QMenu, QPlainTextEdit, 
                               QLineEdit, QToolBar, QMessageBox, QLabel)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import QAction, QFont
from PySide6.QtCore import Qt, QDir

class NexusStudioAnalyzer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("code_Analyzer")
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
            QPushButton#AnalyzeBtn { background: #ce9178; font-weight: bold; color: black; }
            QPushButton#AnalyzeBtn:hover { background: #d7a692; }
            QPushButton#RunBtn { background: #28a745; font-weight: bold; }
            QPushButton#RunBtn:hover { background: #218838; }
            QLabel#HeaderLabel { background: #252526; padding: 8px; font-weight: bold; font-family: Consolas; font-size: 14px; border-bottom: 1px solid #3c3c3c; }
        """)

        self.current_file = None
        self.compare_file = None
        self.is_diff_mode = False
        
        self.setup_ui()
        
    def setup_ui(self):
        # --- 1. TOOLBAR ---
        self.toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        
        # History Controls (Undo/Redo)
        undo_btn = QPushButton("↩ Undo")
        undo_btn.clicked.connect(self.trigger_undo)
        self.toolbar.addWidget(undo_btn)
        
        redo_btn = QPushButton("↪ Redo")
        redo_btn.clicked.connect(self.trigger_redo)
        self.toolbar.addWidget(redo_btn)
        
        self.toolbar.addSeparator()
        
        self.toolbar.addWidget(QLabel(" 🐍 Venv: "))
        self.venv_input = QLineEdit()
        self.venv_input.setPlaceholderText("Path to python.exe")
        self.venv_input.setFixedWidth(200)
        self.toolbar.addWidget(self.venv_input)
        
        # Action Buttons
        save_btn = QPushButton("💾 Save")
        save_btn.setObjectName("ActionBtn")
        save_btn.clicked.connect(self.save_current_file)
        self.toolbar.addWidget(save_btn)

        analyze_btn = QPushButton("🧠 Analyze Code")
        analyze_btn.setObjectName("AnalyzeBtn")
        analyze_btn.clicked.connect(self.analyze_code)
        self.toolbar.addWidget(analyze_btn)

        run_btn = QPushButton("▶ Run")
        run_btn.setObjectName("RunBtn")
        run_btn.clicked.connect(self.execute_code)
        self.toolbar.addWidget(run_btn)

        self.toolbar.addSeparator()
        
        # Modes
        self.edit_mode_btn = QPushButton("📝 Edit Mode")
        self.edit_mode_btn.clicked.connect(self.enable_edit_mode)
        self.toolbar.addWidget(self.edit_mode_btn)

        self.compare_mode_btn = QPushButton("🔍 Compare & Edit")
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

        # --- 4. CENTRAL AREA (Header + Monaco) ---
        central_widget = QWidget()
        central_layout = QVBoxLayout(central_widget)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)

        # The File Name Header
        self.editor_header = QLabel("📝 No File Open")
        self.editor_header.setObjectName("HeaderLabel")
        central_layout.addWidget(self.editor_header)

        self.browser = QWebEngineView()
        central_layout.addWidget(self.browser)
        self.setCentralWidget(central_widget)

        self.init_monaco()

    # --- MONACO ENGINE ---
    def init_monaco(self):
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
                    window.openStandardEditor('# Welcome to Nexus Studio\\n# Double click a file to start editing.\\n');
                });

                function disposeCurrent() {
                    if (currentEditor) { currentEditor.dispose(); currentEditor = null; }
                    container.innerHTML = '';
                }

                window.openStandardEditor = function(code) {
                    disposeCurrent();
                    currentEditor = monaco.editor.create(container, {
                        value: code, language: 'python', theme: 'vs-dark', automaticLayout: true, fontSize: 14
                    });
                };

                window.openDiffEditor = function(oldCode, newCode) {
                    disposeCurrent();
                    currentEditor = monaco.editor.createDiffEditor(container, {
                        theme: 'vs-dark', renderSideBySide: true, automaticLayout: true, fontSize: 14, readOnly: false, originalEditable: false
                    });
                    currentEditor.setModel({
                        original: monaco.editor.createModel(oldCode, 'python'),
                        modified: monaco.editor.createModel(newCode, 'python')
                    });
                };

                window.getEditorValue = function() {
                    if (!currentEditor) return "";
                    if (typeof currentEditor.getModifiedEditor === 'function') {
                        return currentEditor.getModifiedEditor().getValue();
                    }
                    return currentEditor.getValue();
                };

                // UNDO / REDO TRIGGERS
                window.triggerUndo = function() {
                    let ed = (typeof currentEditor.getModifiedEditor === 'function') ? currentEditor.getModifiedEditor() : currentEditor;
                    ed.trigger('keyboard', 'undo', null);
                };
                
                window.triggerRedo = function() {
                    let ed = (typeof currentEditor.getModifiedEditor === 'function') ? currentEditor.getModifiedEditor() : currentEditor;
                    ed.trigger('keyboard', 'redo', null);
                };
            </script>
        </body></html>
        """
        self.browser.setHtml(html)

    def trigger_undo(self):
        self.browser.page().runJavaScript("if(window.triggerUndo) window.triggerUndo();")
        
    def trigger_redo(self):
        self.browser.page().runJavaScript("if(window.triggerRedo) window.triggerRedo();")

    # --- CODE ANALYSIS (AST) ---
    def analyze_code(self):
        """Fetches code from the editor and runs structural analysis on it."""
        self.terminal.appendPlainText("\n--- Running Smart Code Analysis ---")
        self.browser.page().runJavaScript("window.getEditorValue()", self._process_analysis)

    def _process_analysis(self, code):
        if not code.strip():
            self.terminal.appendPlainText("> Code is empty.")
            return
            
        try:
            # Parse the code into an Abstract Syntax Tree
            tree = ast.parse(code)
            
            functions = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            classes = [node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            imports = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import) or isinstance(node, ast.ImportFrom)]
            
            self.terminal.appendPlainText("✅ Syntax Check: PASSED (No critical errors)")
            self.terminal.appendPlainText(f"📦 Imports Detected: {len(imports)} {imports if imports else ''}")
            self.terminal.appendPlainText(f"🏗️ Classes Found: {len(classes)} {classes if classes else ''}")
            self.terminal.appendPlainText(f"🛠️ Functions Found: {len(functions)}")
            for func in functions:
                self.terminal.appendPlainText(f"   - def {func}()")
                
            self.terminal.appendPlainText("-----------------------------------")
            
        except SyntaxError as e:
            # Catch bad syntax before the user even tries to run it
            self.terminal.appendPlainText(f"❌ SYNTAX ERROR DETECTED:")
            self.terminal.appendPlainText(f"Line {e.lineno}, Column {e.offset}: {e.msg}")
            self.terminal.appendPlainText(f"Code: {e.text.strip() if e.text else ''}")

    # --- MODE SWITCHING ---
    def update_header(self, text, is_diff=False):
        color = "#ce9178" if is_diff else "#4ec9b0"
        self.editor_header.setStyleSheet(f"background: #252526; padding: 8px; font-weight: bold; font-family: Consolas; font-size: 14px; border-bottom: 2px solid {color};")
        self.editor_header.setText(text)

    def enable_edit_mode(self):
        self.is_diff_mode = False
        self.edit_mode_btn.setStyleSheet("background: #0e639c;") 
        self.compare_mode_btn.setStyleSheet("")
        
        if self.current_file and os.path.exists(self.current_file):
            with open(self.current_file, 'r', encoding='utf-8') as f: code = f.read()
            self.update_header(f"📝 {self.current_file}")
        else:
            code = "# Select a file to edit"
            self.update_header("📝 No File Open")
            
        safe_code = json.dumps(code)
        self.browser.page().runJavaScript(f"if (window.openStandardEditor) window.openStandardEditor({safe_code});")

    def enable_compare_mode(self):
        if not self.current_file:
            QMessageBox.warning(self, "Compare", "Please open a main file first.")
            return

        file_path, _ = QFileDialog.getOpenFileName(self, "Select Older File to Compare", "", "Python Files (*.py);;All Files (*)")
        if not file_path: return

        self.compare_file = file_path
        self.is_diff_mode = True
        self.compare_mode_btn.setStyleSheet("background: #0e639c;") 
        self.edit_mode_btn.setStyleSheet("")

        with open(self.compare_file, 'r', encoding='utf-8') as f: old_code = f.read()
        with open(self.current_file, 'r', encoding='utf-8') as f: new_code = f.read()

        self.update_header(f"🔍 COMPARING: {os.path.basename(self.compare_file)} (Original) ➔ {os.path.basename(self.current_file)} (Current)", is_diff=True)

        safe_old = json.dumps(old_code)
        safe_new = json.dumps(new_code)
        self.browser.page().runJavaScript(f"if (window.openDiffEditor) window.openDiffEditor({safe_old}, {safe_new});")

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
            self.setWindowTitle(f"Nexus Studio - {os.path.basename(file_path)}")
            self.enable_edit_mode()

    def save_current_file(self):
        if not self.current_file: return
        self.browser.page().runJavaScript("window.getEditorValue()", self._write_to_file)

    def _write_to_file(self, code_content):
        try:
            with open(self.current_file, 'w', encoding='utf-8') as f: f.write(code_content)
            self.terminal.appendPlainText(f"> Saved: {os.path.basename(self.current_file)}")
        except Exception as e:
            self.terminal.appendPlainText(f"> Save Error: {str(e)}")

    def execute_code(self):
        if not self.current_file: return
        self.browser.page().runJavaScript("window.getEditorValue()", self._run_after_save)

    def _run_after_save(self, code_content):
        with open(self.current_file, 'w', encoding='utf-8') as f: f.write(code_content)

        python_exe = self.venv_input.text().strip() or sys.executable
        self.terminal.appendPlainText(f"\n--- Executing: {os.path.basename(self.current_file)} ---")
        
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
    window = NexusStudioAnalyzer()
    window.show()
    sys.exit(app.exec())
