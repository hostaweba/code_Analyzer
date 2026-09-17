import sys
import os
import subprocess
import json
import ast
import builtins
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QPushButton, QFileDialog, QDockWidget, 
                               QTreeView, QFileSystemModel, QPlainTextEdit, 
                               QLineEdit, QToolBar, QTextBrowser,
                               QTabWidget, QStatusBar, QSizePolicy)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt, QDir
from PySide6.QtGui import QAction, QKeySequence

# ==========================================
# 1. DEEP LINTER & EXPLAINER ENGINE (v3.0)
# ==========================================
class ZenithAnalyzer(ast.NodeVisitor):
    def __init__(self):
        self.stats = {"complexity": 1, "loc": 0}
        self.bugs = []
        self.security_alerts = []
        self.functions = {}
        self.current_scope = "Global Scope"
        self.defined_vars = set(dir(builtins))
        self.flowchart = ["graph TD"]
        self.node_id = 0

    def new_node(self):
        self.node_id += 1
        return f"N{self.node_id}"

    def sanitize_mermaid(self, text):
        clean = "".join(c for c in str(text) if c.isalnum() or c in " _=><+-/*.")
        return clean[:40] + ("..." if len(clean) > 40 else "")

    def get_text(self, node):
        try: return ast.unparse(node)
        except: return "expression"

    def visit_Import(self, node):
        for alias in node.names: self.defined_vars.add(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        for alias in node.names: self.defined_vars.add(alias.name)
        self.generic_visit(node)

    def visit_Assign(self, node):
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        for t in targets: self.defined_vars.add(t)
        val = self.get_text(node.value)
        if self.current_scope in self.functions: 
            self.functions[self.current_scope]["logic"].append(f"Assigns '{val}' to: {', '.join(targets)}")
        self.generic_visit(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.defined_vars:
            if node.id not in ["self", "args", "kwargs", "cls"]:
                self.bugs.append(f"Line {node.lineno}: WARNING - Variable '{node.id}' used before assignment.")
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        prev_scope = self.current_scope
        self.current_scope = node.name
        
        for default in node.args.defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.bugs.append(f"Line {node.lineno}: CRITICAL - Mutable default argument in '{node.name}()'.")

        for arg in node.args.args: self.defined_vars.add(arg.arg)
        
        doc = ast.get_docstring(node)
        if not doc:
            self.bugs.append(f"Line {node.lineno}: INFO - Function '{node.name}()' missing docstring.")
            
        desc = f"Purpose: {doc}" if doc else f"Accepts parameters: {', '.join([a.arg for a in node.args.args])}"
        self.functions[node.name] = {"logic": [desc], "returns": "None"}
        
        has_return = False
        for child in node.body:
            if has_return:
                self.bugs.append(f"Line {child.lineno}: ERROR - Unreachable code after return in '{node.name}()'.")
                break
            if isinstance(child, ast.Return): has_return = True
        
        self.generic_visit(node)
        self.current_scope = prev_scope

    def visit_Return(self, node):
        val = self.get_text(node.value) if node.value else "Nothing"
        if self.current_scope in self.functions:
            self.functions[self.current_scope]["logic"].append(f"Returns: {val}")
            self.functions[self.current_scope]["returns"] = val
        self.generic_visit(node)

    def visit_If(self, node):
        self.stats["complexity"] += 1
        cond = self.get_text(node.test)
        if self.current_scope in self.functions:
            self.functions[self.current_scope]["logic"].append(f"Checks condition: IF {cond}")
        self.generic_visit(node)

    def visit_For(self, node):
        self.stats["complexity"] += 1
        self.generic_visit(node)

    def visit_While(self, node):
        self.stats["complexity"] += 1
        self.generic_visit(node)

    def visit_Call(self, node):
        func_name = self.get_text(node.func)
        if func_name in ['eval', 'exec', 'os.system', 'subprocess.call']:
            self.security_alerts.append(f"Line {node.lineno}: THREAT - Dangerous function execution '{func_name}()'.")
        elif func_name == 'print':
            self.bugs.append(f"Line {node.lineno}: INFO - 'print' found. Use 'logging' for production.")
        self.generic_visit(node)

    def visit_ExceptHandler(self, node):
        if node.type is None:
            self.security_alerts.append(f"Line {node.lineno}: VULNERABILITY - Bare 'except:' clause masks critical system faults.")
        self.generic_visit(node)

    def build_flow(self, nodes, parent_id):
        curr_parent = parent_id
        for node in nodes:
            nid = self.new_node()
            if isinstance(node, ast.Assign):
                lbl = self.sanitize_mermaid(f"Assign: {self.get_text(node)}")
                self.flowchart.append(f"  {curr_parent} --> {nid}[{lbl}]")
                curr_parent = nid
            elif isinstance(node, ast.If):
                cond = self.sanitize_mermaid(self.get_text(node.test))
                self.flowchart.append(f"  {curr_parent} --> {nid}{{{cond}?}}")
                t_start = self.new_node()
                self.flowchart.append(f"  {nid} -- Yes --> {t_start}(True)")
                last_t = self.build_flow(node.body, t_start)
                last_f = nid
                if node.orelse:
                    f_start = self.new_node()
                    self.flowchart.append(f"  {nid} -- No --> {f_start}(False)")
                    last_f = self.build_flow(node.orelse, f_start)
                merge = self.new_node()
                self.flowchart.append(f"  {last_t} --> {merge}((Merge))")
                self.flowchart.append(f"  {last_f} --> {merge}")
                curr_parent = merge
            elif isinstance(node, ast.Return):
                lbl = self.sanitize_mermaid(f"Return: {self.get_text(node.value) if node.value else 'None'}")
                self.flowchart.append(f"  {curr_parent} --> {nid}([{lbl}])")
                curr_parent = nid
        return curr_parent


def process_ast(code_string):
    res = {"status": "SUCCESS", "bugs": [], "security": [], "english": "", "graph": "", "stats": {"loc": len(code_string.splitlines()), "complexity": 1}}
    try:
        tree = ast.parse(code_string)
        analyzer = ZenithAnalyzer()
        analyzer.visit(tree)
        
        res["bugs"] = analyzer.bugs
        res["security"] = analyzer.security_alerts
        res["stats"]["complexity"] = analyzer.stats["complexity"]
        
        html = "<div style='font-family: Arial; padding: 10px;'>"
        for fn, data in analyzer.functions.items():
            html += f"<div style='background:#252526; padding:10px; margin-bottom:10px; border-left:4px solid #4ec9b0;'><h3 style='margin:0; color:#4ec9b0;'>{fn}()</h3><ul style='color:#d4d4d4;'>"
            for step in data["logic"]: html += f"<li style='margin-bottom:3px;'>{step}</li>"
            html += f"</ul><p style='color:#c586c0; margin:0;'>Returns: {data['returns']}</p></div>"
        res["english"] = html + "</div>"
        
        funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
        if not funcs: funcs = [tree]
        for func in funcs:
            name = func.name if hasattr(func, 'name') else "Main"
            start = analyzer.new_node()
            analyzer.flowchart.append(f"  {start}([{name} START])")
            last = analyzer.build_flow(func.body, start)
            end = analyzer.new_node()
            analyzer.flowchart.append(f"  {last} --> {end}([{name} END])")
            analyzer.flowchart.append(f"  style {start} fill:#0e639c,color:#fff")
            analyzer.flowchart.append(f"  style {end} fill:#f44747,color:#fff")
        res["graph"] = "\n".join(analyzer.flowchart)
        
    except SyntaxError as e:
        res["status"] = "ERROR"
        res["bugs"].append(f"SYNTAX ERROR Line {e.lineno}: {e.msg}")
        res["graph"] = "graph TD\n A[Syntax Error]"
    return res


# ==========================================
# 2. MAIN IDE GUI (Refined Focus Mode)
# ==========================================
class NexusStudioZenith(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Code_Analyzer")
        self.resize(1600, 900)
        self.setStyleSheet("""
            QMainWindow { background-color: #1e1e1e; color: #cccccc; }
            QMenuBar { background-color: #2d2d30; color: white; padding: 2px; border-bottom: 1px solid #111;}
            QMenuBar::item:selected { background: #505050; }
            QMenu { background-color: #252526; color: white; border: 1px solid #444; }
            QDockWidget { font-weight: bold; color: #cccccc; }
            QDockWidget::title { background: #252526; padding: 6px; border-bottom: 1px solid #111; }
            QTreeView { background: #252526; color: #d4d4d4; border: none; font-family: 'Segoe UI'; font-size: 13px; }
            QPlainTextEdit, QLineEdit, QTextBrowser { background: #1e1e1e; color: #d4d4d4; border: none; font-family: Consolas; }
            QToolBar { background: #333333; border: none; padding: 4px; border-bottom: 1px solid #111; }
            QPushButton { background: transparent; color: #cccccc; border-radius: 4px; padding: 6px 12px; margin: 2px; font-weight:bold;}
            QPushButton:hover { background: #505050; color: white; }
            QPushButton:checked { background: #0e639c; color: white; } 
            QPushButton#ActionBtn { background: #0e639c; color: white; }
            QPushButton#AnalyzeBtn { background: #c586c0; color: white; }
            QPushButton#RunBtn { background: #4ec9b0; color: black; }
            QTabWidget::pane { border: none; border-top: 1px solid #333; }
            QTabBar::tab { background: #2d2d2d; color: #858585; padding: 8px 15px; border-right: 1px solid #333; }
            QTabBar::tab:selected { background: #1e1e1e; color: #d4d4d4; border-top: 2px solid #0e639c; }
            QStatusBar { background: #007acc; color: white; font-weight: bold; }
        """)

        self.current_file = None
        self.compare_target = None  # Tracks the second file during comparison
        
        self.setup_actions()
        self.setup_ui()
        
    def setup_actions(self):
        self.action_open_folder = QAction("Open Workspace...", self)
        self.action_open_folder.setShortcut(QKeySequence("Ctrl+O"))
        self.action_open_folder.triggered.connect(self.set_project_root)

        self.action_compare = QAction("Compare with File...", self)
        self.action_compare.triggered.connect(self.enable_compare_mode)

    def setup_ui(self):
        menubar = self.menuBar()
        file_menu = menubar.addMenu("File")
        file_menu.addAction(self.action_open_folder)
        file_menu.addAction(self.action_compare)
        
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("NexusVirtualManager Core Ready")

        # -- TOOLBAR --
        self.toolbar = QToolBar("Main Toolbar")
        self.toolbar.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, self.toolbar)
        
        self.btn_toggle_explorer = QPushButton("🗂️ Explorer"); self.btn_toggle_explorer.setCheckable(True)
        self.btn_toggle_explorer.clicked.connect(lambda: self.toggle_panel(self.explorer_dock, self.btn_toggle_explorer))
        self.toolbar.addWidget(self.btn_toggle_explorer)
        
        self.btn_toggle_diagnostics = QPushButton("🔬 Diagnostics"); self.btn_toggle_diagnostics.setCheckable(True)
        self.btn_toggle_diagnostics.clicked.connect(lambda: self.toggle_panel(self.insight_dock, self.btn_toggle_diagnostics))
        self.toolbar.addWidget(self.btn_toggle_diagnostics)

        self.btn_toggle_terminal = QPushButton("💻 Terminal"); self.btn_toggle_terminal.setCheckable(True)
        self.btn_toggle_terminal.clicked.connect(lambda: self.toggle_panel(self.terminal_dock, self.btn_toggle_terminal))
        self.toolbar.addWidget(self.btn_toggle_terminal)

        btn_zen = QPushButton("🧘 Focus Mode")
        btn_zen.clicked.connect(self.activate_zen_mode)
        self.toolbar.addWidget(btn_zen)

        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.toolbar.addWidget(spacer)

        self.toolbar.addWidget(QPushButton("💾 Save", objectName="ActionBtn", clicked=self.save_file))
        self.toolbar.addWidget(QPushButton("🔍 Analyze Code", objectName="AnalyzeBtn", clicked=self.run_master_analysis))
        self.toolbar.addWidget(QPushButton("▶ Execute", objectName="RunBtn", clicked=self.execute_code))

        # -- PANELS --
        self.explorer_dock = QDockWidget("Workspace", self)
        self.file_model = QFileSystemModel(); self.file_model.setRootPath(QDir.currentPath())
        self.tree_view = QTreeView(); self.tree_view.setModel(self.file_model); self.tree_view.setRootIndex(self.file_model.index(QDir.currentPath()))
        self.tree_view.setColumnWidth(0, 220); [self.tree_view.hideColumn(i) for i in range(1,4)]
        self.tree_view.doubleClicked.connect(self.load_file)
        self.explorer_dock.setWidget(self.tree_view)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.explorer_dock)

        self.insight_dock = QDockWidget("Telemetry & Diagnostics", self)
        self.tabs = QTabWidget()
        self.bug_view = QTextBrowser(); self.sec_view = QTextBrowser(); self.diff_view = QTextBrowser()
        self.english_view = QTextBrowser(); self.graph_view = QWebEngineView()
        self.init_mermaid()
        
        self.tabs.addTab(self.bug_view, "🐞 Quality")
        self.tabs.addTab(self.sec_view, "🛡️ Security")
        self.tabs.addTab(self.diff_view, "⚖️ Diff Analytics")
        self.tabs.addTab(self.english_view, "📖 Logic")
        self.tabs.addTab(self.graph_view, "🗺️ Architecture")
        self.insight_dock.setWidget(self.tabs)
        self.addDockWidget(Qt.RightDockWidgetArea, self.insight_dock)

        self.terminal_dock = QDockWidget("System Output", self)
        self.terminal = QPlainTextEdit(); self.terminal.setReadOnly(True)
        self.terminal_dock.setWidget(self.terminal)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.terminal_dock)

        # -- CENTRAL EDITOR (Clean layout, no header) --
        central = QWidget()
        layout = QVBoxLayout(central); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        self.browser = QWebEngineView()
        layout.addWidget(self.browser)
        self.setCentralWidget(central)
        self.init_monaco()

        self.activate_zen_mode()

    def toggle_panel(self, dock_widget, button):
        is_visible = dock_widget.isVisible()
        dock_widget.setVisible(not is_visible)
        button.setChecked(not is_visible)

    def activate_zen_mode(self):
        self.explorer_dock.hide()
        self.insight_dock.hide()
        self.terminal_dock.hide()
        self.btn_toggle_explorer.setChecked(False)
        self.btn_toggle_diagnostics.setChecked(False)
        self.btn_toggle_terminal.setChecked(False)

    # --- MONACO INJECTION ---
    def init_monaco(self):
        html = """<!DOCTYPE html><html><head><style>body, html { margin: 0; height: 100%; overflow: hidden; background-color: #1e1e1e; }</style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs/loader.min.js"></script></head><body>
            <div id="container" style="height:100%;"></div><script>
                var ed = null;
                require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs' } });
                require(['vs/editor/editor.main'], function() { window.openStandard('# Workspace initialized.\\n# Use the top toolbar to toggle panels.\\n'); });
                function dispose() { if(ed) ed.dispose(); document.getElementById('container').innerHTML = ''; }
                window.openStandard = function(code) { 
                    dispose(); 
                    ed = monaco.editor.create(document.getElementById('container'), { value: code, language: 'python', theme: 'vs-dark', automaticLayout: true, minimap: { enabled: false } }); 
                };
                window.openDiff = function(oldC, newC) { 
                    dispose(); 
                    // Added originalEditable: true so BOTH sides can be edited and saved
                    ed = monaco.editor.createDiffEditor(document.getElementById('container'), { theme: 'vs-dark', renderSideBySide: true, automaticLayout: true, originalEditable: true }); 
                    ed.setModel({ original: monaco.editor.createModel(oldC, 'python'), modified: monaco.editor.createModel(newC, 'python') }); 
                };
                window.getState = function() {
                    if (!ed) return JSON.stringify({mode: 'none'});
                    if (typeof ed.getModifiedEditor === 'function') return JSON.stringify({ mode: 'diff', old: ed.getOriginalEditor().getValue(), new: ed.getModifiedEditor().getValue() });
                    return JSON.stringify({ mode: 'single', code: ed.getValue() });
                };
            </script></body></html>"""
        self.browser.setHtml(html)

    def init_mermaid(self):
        html = """<!DOCTYPE html><html><head>
            <style>body { background:#1e1e1e; margin:0; height:100vh; overflow:hidden;} #g { width:100%; height:100%; display:flex; justify-content:center; align-items:center; } svg {width:100%!important; height:100%!important;} </style>
            <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
            <script>
                mermaid.initialize({startOnLoad:false, theme:'dark'});
                window.drawGraph = async function(def) {
                    try { const { svg } = await mermaid.render('svgId', def); document.getElementById('g').innerHTML = svg; }
                    catch (e) { document.getElementById('g').innerHTML = "<p style='color:red;'>Syntax too complex for visualization.</p>"; }
                };
            </script></head><body><div id="g"><p style="color:#858585;">Awaiting Analysis...</p></div></body></html>"""
        self.graph_view.setHtml(html)

    def set_project_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Workspace")
        if folder:
            self.file_model.setRootPath(folder)
            self.tree_view.setRootIndex(self.file_model.index(folder))
            self.explorer_dock.show()
            self.btn_toggle_explorer.setChecked(True)

    def load_file(self, index):
        path = self.file_model.filePath(index)
        if os.path.isfile(path): 
            self.current_file = path
            self.compare_target = None # Reset compare target on normal open
            with open(path, 'r', encoding='utf-8') as f: code = f.read()
            
            # Using Window Title & Status bar to save space
            self.setWindowTitle(f"NexusVirtualManager — 📝 {os.path.basename(path)}")
            self.status_bar.showMessage(f"Editing: {path}")
            
            self.browser.page().runJavaScript(f"if(window.openStandard) window.openStandard({json.dumps(code)});")

    def enable_compare_mode(self):
        if not self.current_file: return
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Origin File", "", "Python (*.py)")
        if not file_path: return
        
        self.compare_target = file_path # Store this so we can save it later
        
        with open(file_path, 'r', encoding='utf-8') as f: old_c = f.read()
        with open(self.current_file, 'r', encoding='utf-8') as f: new_c = f.read()
        
        # Using Window Title & Status bar
        title = f"⚖️ Comparing: {os.path.basename(file_path)} (Left) vs {os.path.basename(self.current_file)} (Right)"
        self.setWindowTitle(f"NexusVirtualManager — {title}")
        self.status_bar.showMessage(title)
        
        self.browser.page().runJavaScript(f"if(window.openDiff) window.openDiff({json.dumps(old_c)}, {json.dumps(new_c)});")

    def save_file(self):
        self.browser.page().runJavaScript("window.getState()", self._save)

    def _save(self, json_str):
        data = json.loads(json_str)
        if not self.current_file or data['mode'] == 'none': return
        
        # Handle Single File Save
        if data['mode'] == 'single':
            with open(self.current_file, 'w', encoding='utf-8') as f: f.write(data['code'])
            self.terminal.appendPlainText(f"[IO] Saved {os.path.basename(self.current_file)}")
            
        # Handle Double File Save (Diff Mode)
        elif data['mode'] == 'diff':
            with open(self.current_file, 'w', encoding='utf-8') as f: f.write(data['new'])
            self.terminal.appendPlainText(f"[IO] Saved Right Pane: {os.path.basename(self.current_file)}")
            
            if self.compare_target:
                with open(self.compare_target, 'w', encoding='utf-8') as f: f.write(data['old'])
                self.terminal.appendPlainText(f"[IO] Saved Left Pane: {os.path.basename(self.compare_target)}")

    def execute_code(self):
        self._save('{"mode":"single", "code":""}')
        self.terminal_dock.show()
        self.btn_toggle_terminal.setChecked(True)
        self.terminal.appendPlainText(f"\n[EXEC] Running architecture...")
        subprocess.Popen([sys.executable, self.current_file], cwd=os.path.dirname(self.current_file))

    def run_master_analysis(self):
        self.insight_dock.show()
        self.btn_toggle_diagnostics.setChecked(True)
        self.terminal.appendPlainText("[DIAGNOSTICS] Commencing AST Analysis...")
        self.browser.page().runJavaScript("window.getState()", self._route_analysis)

    def _route_analysis(self, json_str):
        data = json.loads(json_str)
        if data['mode'] == 'none': return
        
        new_res = process_ast(data['new'] if data['mode'] == 'diff' else data['code'])
        
        b_html = f"<div style='padding:10px;'><h2 style='color:#c586c0;'>Code Quality Report</h2><p>Complexity: {new_res['stats']['complexity']} | LOC: {new_res['stats']['loc']}</p><hr><ul>"
        for bug in new_res['bugs']: b_html += f"<li style='color:#d7ba7d; margin-bottom:5px;'>{bug}</li>"
        self.bug_view.setHtml(b_html + "</ul></div>")

        s_html = "<div style='padding:10px;'><h2 style='color:#f44747;'>Security Audit</h2><hr><ul>"
        if not new_res['security']: s_html += "<li style='color:#4ec9b0;'>Zero vulnerabilities detected.</li>"
        for sec in new_res['security']: s_html += f"<li style='color:#f44747; margin-bottom:5px;'>{sec}</li>"
        self.sec_view.setHtml(s_html + "</ul></div>")

        if data['mode'] == 'diff':
            old_res = process_ast(data['old'])
            c_diff = new_res['stats']['complexity'] - old_res['stats']['complexity']
            l_diff = new_res['stats']['loc'] - old_res['stats']['loc']
            
            d_html = f"<div style='padding:10px;'><h2 style='color:#0e639c;'>Differential Analytics</h2><hr>"
            d_html += f"<h3>Metrics Delta</h3><p>Complexity Shift: <b>{'+' if c_diff > 0 else ''}{c_diff}</b></p>"
            d_html += f"<p>LOC Shift: <b>{'+' if l_diff > 0 else ''}{l_diff}</b></p>"
            
            new_bugs = set(new_res['bugs']) - set(old_res['bugs'])
            fixed_bugs = set(old_res['bugs']) - set(new_res['bugs'])
            
            d_html += "<h3>Regressions Introduced</h3><ul>"
            for b in new_bugs: d_html += f"<li style='color:#f44747;'>{b}</li>"
            d_html += "</ul><h3>Issues Resolved</h3><ul>"
            for b in fixed_bugs: d_html += f"<li style='color:#4ec9b0;'>{b}</li>"
            self.diff_view.setHtml(d_html + "</ul></div>")
        else:
            self.diff_view.setHtml("<div style='padding:10px; color:#858585;'>Open two files via File > Compare to view differential analytics.</div>")

        self.english_view.setHtml(new_res['english'])
        if new_res['status'] == "SUCCESS":
            self.graph_view.page().runJavaScript(f"if(window.drawGraph) window.drawGraph({json.dumps(new_res['graph'])});")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = NexusStudioZenith()
    window.show()
    sys.exit(app.exec())
