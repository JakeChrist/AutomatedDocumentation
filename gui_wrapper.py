import sys
import subprocess
from PyQt5 import QtWidgets, QtCore


class PathLineEdit(QtWidgets.QLineEdit):
    """QLineEdit that accepts drag-and-drop of files/folders."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            self.setText(urls[0].toLocalFile())


class CollapsibleBox(QtWidgets.QWidget):
    """Simple collapsible container."""

    def __init__(self, title="", parent=None):
        super().__init__(parent)
        self.toggle_button = QtWidgets.QToolButton(text=title, checkable=True)
        self.toggle_button.setStyleSheet("QToolButton { border: none; }")
        self.toggle_button.setToolButtonStyle(QtCore.Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setArrowType(QtCore.Qt.RightArrow)
        self.toggle_button.clicked.connect(self.on_toggled)

        self.content = QtWidgets.QWidget()
        self.content.setVisible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content)

    def on_toggled(self):
        checked = self.toggle_button.isChecked()
        arrow = QtCore.Qt.DownArrow if checked else QtCore.Qt.RightArrow
        self.toggle_button.setArrowType(arrow)
        self.content.setVisible(checked)

    def setContentLayout(self, layout):
        self.content.setLayout(layout)


class CommandRunner(QtCore.QThread):
    """Runs one or more commands in a worker thread."""

    output = QtCore.pyqtSignal(str)
    finished = QtCore.pyqtSignal(int)

    def __init__(self, cmds):
        super().__init__()
        self.cmds = cmds

    def run(self):
        rc = 0
        for cmd in self.cmds:
            self.output.emit(f"$ {' '.join(cmd)}\n")
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.stdout:
                    self.output.emit(result.stdout)
                if result.stderr:
                    self.output.emit(result.stderr)
                rc = result.returncode
                if rc != 0:
                    break
            except Exception as exc:
                self.output.emit(str(exc))
                rc = -1
                break
        self.finished.emit(rc)


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Documentation GUI")

        # Project directory selector
        self.project_edit = PathLineEdit()
        project_btn = QtWidgets.QPushButton("Browse…")
        project_btn.clicked.connect(lambda: self.select_dir(self.project_edit))
        project_layout = QtWidgets.QHBoxLayout()
        project_layout.addWidget(QtWidgets.QLabel("Project Directory:"))
        project_layout.addWidget(self.project_edit)
        project_layout.addWidget(project_btn)

        # Output directory selector
        self.output_edit = PathLineEdit()
        output_btn = QtWidgets.QPushButton("Browse…")
        output_btn.clicked.connect(lambda: self.select_dir(self.output_edit))
        output_layout = QtWidgets.QHBoxLayout()
        output_layout.addWidget(QtWidgets.QLabel("Output Directory:"))
        output_layout.addWidget(self.output_edit)
        output_layout.addWidget(output_btn)

        # DocGen options
        self.docgen_private_cb = QtWidgets.QCheckBox("Include private functions")
        self.lang_py_cb = QtWidgets.QCheckBox("Python")
        self.lang_matlab_cb = QtWidgets.QCheckBox("MATLAB")
        docgen_layout = QtWidgets.QVBoxLayout()
        docgen_layout.addWidget(self.docgen_private_cb)
        lang_layout = QtWidgets.QHBoxLayout()
        lang_layout.addWidget(QtWidgets.QLabel("Languages:"))
        lang_layout.addWidget(self.lang_py_cb)
        lang_layout.addWidget(self.lang_matlab_cb)
        lang_layout.addStretch()
        docgen_layout.addLayout(lang_layout)
        docgen_box = CollapsibleBox("DocGen Options")
        docgen_box.setContentLayout(docgen_layout)

        # ExplainCode options
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(["HTML", "PDF"])
        format_layout = QtWidgets.QHBoxLayout()
        format_layout.addWidget(QtWidgets.QLabel("Output format:"))
        format_layout.addWidget(self.format_combo)
        format_layout.addStretch()

        self.include_data_cb = QtWidgets.QCheckBox("Include input data analysis")
        self.data_edit = PathLineEdit()
        self.data_edit.setEnabled(False)
        data_btn = QtWidgets.QPushButton("Browse…")
        data_btn.setEnabled(False)
        data_btn.clicked.connect(lambda: self.select_file(self.data_edit))
        self.include_data_cb.toggled.connect(
            lambda v: (self.data_edit.setEnabled(v), data_btn.setEnabled(v))
        )
        data_layout = QtWidgets.QHBoxLayout()
        data_layout.addWidget(self.data_edit)
        data_layout.addWidget(data_btn)

        explain_layout = QtWidgets.QVBoxLayout()
        explain_layout.addLayout(format_layout)
        explain_layout.addWidget(self.include_data_cb)
        explain_layout.addLayout(data_layout)
        explain_box = CollapsibleBox("ExplainCode Options")
        explain_box.setContentLayout(explain_layout)

        # Log area
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)

        # Buttons
        self.docgen_btn = QtWidgets.QPushButton("Run DocGen")
        self.explain_btn = QtWidgets.QPushButton("Run ExplainCode")
        self.both_btn = QtWidgets.QPushButton("Run Both")
        self.docgen_btn.clicked.connect(self.run_docgen)
        self.explain_btn.clicked.connect(self.run_explain)
        self.both_btn.clicked.connect(self.run_both)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(self.docgen_btn)
        button_layout.addWidget(self.explain_btn)
        button_layout.addWidget(self.both_btn)

        # Main layout
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.addLayout(project_layout)
        main_layout.addLayout(output_layout)
        main_layout.addWidget(docgen_box)
        main_layout.addWidget(explain_box)
        main_layout.addWidget(self.log)
        main_layout.addLayout(button_layout)

    # Utility methods
    def select_dir(self, line_edit):
        directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select Directory")
        if directory:
            line_edit.setText(directory)

    def select_file(self, line_edit):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Data File", "", "Data Files (*.json *.csv *.txt);;All Files (*)"
        )
        if path:
            line_edit.setText(path)

    def append_log(self, text):
        self.log.appendPlainText(text)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    def set_running(self, running):
        for btn in (self.docgen_btn, self.explain_btn, self.both_btn):
            btn.setEnabled(not running)

    def run_commands(self, cmds):
        if not self.project_edit.text() or not self.output_edit.text():
            self.append_log("Project and output directories must be set.\n")
            return
        self.set_running(True)
        self.runner = CommandRunner(cmds)
        self.runner.output.connect(self.append_log)
        self.runner.finished.connect(self.on_finished)
        self.runner.start()

    def on_finished(self, code):
        self.append_log(f"Process finished with exit code {code}\n")
        self.set_running(False)

    def build_docgen_cmd(self):
        cmd = [
            "docgen",
            "--path",
            self.project_edit.text(),
            "--output",
            self.output_edit.text(),
        ]
        if self.docgen_private_cb.isChecked():
            cmd.append("--include-private")
        langs = []
        if self.lang_py_cb.isChecked():
            langs.append("python")
        if self.lang_matlab_cb.isChecked():
            langs.append("matlab")
        if langs:
            cmd.extend(["--languages", ",".join(langs)])
        return cmd

    def build_explain_cmd(self):
        cmd = [
            "explaincode",
            "--path",
            self.project_edit.text(),
            "--output",
            self.output_edit.text(),
            "--output-format",
            self.format_combo.currentText().lower(),
        ]
        if self.include_data_cb.isChecked() and self.data_edit.text():
            cmd.extend(["--data", self.data_edit.text()])
        return cmd

    def run_docgen(self):
        self.log.clear()
        self.run_commands([self.build_docgen_cmd()])

    def run_explain(self):
        self.log.clear()
        self.run_commands([self.build_explain_cmd()])

    def run_both(self):
        self.log.clear()
        self.run_commands([self.build_docgen_cmd(), self.build_explain_cmd()])


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.resize(700, 500)
    window.show()
    sys.exit(app.exec_())
