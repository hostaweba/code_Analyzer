import sys
import json
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QPlainTextEdit, QPushButton, QSplitter, QLabel)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtCore import Qt

class NexusDiffPro(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Code_Analyzer")
        self.resize(1400, 850)
        self.setStyleSheet("background-color: #1e1e1e; color: #cccccc;")
        
        # Main Container
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        
        # Splitter to separate inputs (left) and diff viewer (right)
        self.splitter = QSplitter(Qt.Horizontal)
        
        # --- LEFT PANEL: Code Inputs ---
        input_widget = QWidget()
        input_layout = QVBoxLayout(input_widget)
        input_layout.setContentsMargins(0, 0, 0, 0)
        
        # Styling for the input boxes
        editor_style = """
            QPlainTextEdit {
                background-color: #252526;
                color: #d4d4d4;
                border: 1px solid #3c3c3c;
                font-family: Consolas, 'Courier New', monospace;
                font-size: 11pt;
                padding: 5px;
            }
        """
        
        self.old_code_input = QPlainTextEdit()
        self.old_code_input.setPlaceholderText("Paste original version here...")
        self.old_code_input.setStyleSheet(editor_style)
        
        self.new_code_input = QPlainTextEdit()
        self.new_code_input.setPlaceholderText("Paste modified version here...")
        self.new_code_input.setStyleSheet(editor_style)
        
        self.compare_btn = QPushButton("🚀 Run Deep Comparison")
        self.compare_btn.setStyleSheet("""
            QPushButton {
                background-color: #0e639c;
                color: white;
                font-weight: bold;
                padding: 12px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background-color: #1177bb; }
        """)
        self.compare_btn.clicked.connect(self.update_diff)
        
        input_layout.addWidget(QLabel("<b>Original Code (Version A)</b>"))
        input_layout.addWidget(self.old_code_input)
        input_layout.addWidget(QLabel("<b>Modified Code (Version B)</b>"))
        input_layout.addWidget(self.new_code_input)
        input_layout.addWidget(self.compare_btn)
        
        # --- RIGHT PANEL: Embedded Monaco Diff Viewer ---
        self.browser = QWebEngineView()
        
        self.splitter.addWidget(input_widget)
        self.splitter.addWidget(self.browser)
        self.splitter.setSizes([400, 1000]) # Give the diff viewer more horizontal space
        
        layout.addWidget(self.splitter)
        
        # Load the base HTML/JS environment
        self.init_monaco()

    def init_monaco(self):
        """Injects the VS Code Monaco diff engine into the browser widget."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body, html { margin: 0; padding: 0; height: 100%; overflow: hidden; background-color: #1e1e1e; }
                #container { height: 100%; width: 100%; }
            </style>
            <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs/loader.min.js"></script>
        </head>
        <body>
            <div id="container"></div>
            <script>
                var diffEditor;
                require.config({ paths: { 'vs': 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.39.0/min/vs' } });
                
                require(['vs/editor/editor.main'], function() {
                    // Initialize the Diff Editor
                    diffEditor = monaco.editor.createDiffEditor(document.getElementById('container'), {
                        theme: 'vs-dark',
                        renderSideBySide: true,     // True for side-by-side, False for inline
                        readOnly: true,
                        automaticLayout: true,
                        ignoreTrimWhitespace: false // Shows if you added/removed spaces
                    });
                    
                    // This function gets called from PySide6 to push new code into the UI
                    window.updateDiff = function(oldCode, newCode) {
                        diffEditor.setModel({
                            original: monaco.editor.createModel(oldCode, 'python'),
                            modified: monaco.editor.createModel(newCode, 'python')
                        });
                    };
                });
            </script>
        </body>
        </html>
        """
        self.browser.setHtml(html)

    def update_diff(self):
        """Passes the PySide text into the JavaScript diff engine."""
        old_code = self.old_code_input.toPlainText()
        new_code = self.new_code_input.toPlainText()
        
        # Safely serialize Python strings to JavaScript-compatible strings
        safe_old = json.dumps(old_code)
        safe_new = json.dumps(new_code)
        
        # Execute the Javascript function defined in the HTML
        js_command = f"if (window.updateDiff) {{ window.updateDiff({safe_old}, {safe_new}); }}"
        self.browser.page().runJavaScript(js_command)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # Enable High DPI scaling for crisp fonts
    app.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    
    window = NexusDiffPro()
    window.show()
    
    # Pre-load some dummy data to demonstrate the capability immediately
    demo_old = "def calculate_discount(price):\n    # Calculate a 10% discount\n    discount = price * 0.10\n    return price - discount"
    demo_new = "def calculate_discount(price, rate=0.10):\n    # Calculate a variable discount\n    if price < 0:\n        return 0\n    discount = price * rate\n    return price - discount"
    
    window.old_code_input.setPlainText(demo_old)
    window.new_code_input.setPlainText(demo_new)
    
    sys.exit(app.exec())
