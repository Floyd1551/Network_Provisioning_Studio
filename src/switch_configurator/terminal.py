"""Exclusive raw serial terminal for login, enable, and manual troubleshooting."""
import queue
import re
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QTextCursor, QFont
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPlainTextEdit, QLineEdit, QPushButton, QCheckBox


class ConsoleWorker(QThread):
    output = Signal(str)
    failure = Signal(str)

    def __init__(self, port, baud):
        super().__init__()
        self.port, self.baud = port, baud
        self.pending = queue.Queue()

    def run(self):
        import serial
        try:
            with serial.Serial(self.port, self.baud, timeout=0.1, write_timeout=2,
                               bytesize=8, parity="N", stopbits=1, xonxoff=False, rtscts=False) as connection:
                connection.write(b"\r")
                while not self.isInterruptionRequested():
                    try: connection.write(self.pending.get_nowait())
                    except queue.Empty: pass
                    chunk = connection.read(max(1, connection.in_waiting))
                    if chunk: self.output.emit(chunk.decode("utf-8", errors="replace"))
        except Exception as error: self.failure.emit(str(error))


class TerminalDialog(QDialog):
    def __init__(self, port, baud, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Raw serial console • {port} • {baud} 8N1")
        self.resize(980, 700)
        self.setModal(True)
        layout = QVBoxLayout(self)
        hint = QLabel("Manual console: commands are sent exactly as entered, without model validation or automatic verification.\nLog in and leave privileged EXEC (#), Junos operational (user@host>), or EXOS (switch.1 #) before connecting.\nOutput stays in this window; it is not written to the activity database.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("Consolas", 10))
        self.output.document().setMaximumBlockCount(10000)
        layout.addWidget(self.output)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("Console input; Enter sends CR (empty input sends Enter)")
        self.input.returnPressed.connect(self.send)
        row.addWidget(self.input)
        hidden = QCheckBox("Hide input")
        hidden.setChecked(True)
        self.input.setEchoMode(QLineEdit.EchoMode.Password)
        hidden.toggled.connect(lambda checked: self.input.setEchoMode(QLineEdit.EchoMode.Password if checked else QLineEdit.EchoMode.Normal))
        row.addWidget(hidden)
        send = QPushButton("Send")
        send.clicked.connect(self.send)
        row.addWidget(send)
        layout.addLayout(row)
        controls = QHBoxLayout()
        for title, data in (("Ctrl+C", b"\x03"), ("Space / next page", b" "), ("Ctrl+Z / end", b"\x1a")):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, payload=data: self.worker.pending.put(payload))
            controls.addWidget(button)
        close = QPushButton("Close console")
        close.clicked.connect(self.close)
        controls.addWidget(close)
        layout.addLayout(controls)
        self.worker = ConsoleWorker(port, baud)
        self.worker.output.connect(self.append)
        self.worker.failure.connect(lambda error: self.append("\nSERIAL ERROR: " + error))
        self.worker.start()

    def append(self, text):
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text).replace("\r", "")
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for character in text:
            if character == "\b": cursor.deletePreviousChar()
            else: cursor.insertText(character)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def send(self):
        self.worker.pending.put(self.input.text().encode("utf-8") + b"\r")
        self.input.clear()

    def done(self, result):
        self.worker.requestInterruption()
        self.worker.wait(3500)
        if self.worker.isRunning(): return
        super().done(result)

    def closeEvent(self, event):
        self.worker.requestInterruption()
        self.worker.wait(3500)
        if self.worker.isRunning(): event.ignore()
        else: event.accept()
