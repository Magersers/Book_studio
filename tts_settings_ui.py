"""Speech backend setup with asynchronous SSH, byte progress and cancellation."""
import threading

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QProgressBar, QFileDialog, QFrame, QCheckBox)

from ui_language import tr
import tts_settings as preferences

_tasks = set()


class ServerTask(QObject):
    progress = Signal(object)
    result = Signal(bool, str)
    finished = Signal()

    def __init__(self, config, install):
        super().__init__()
        self.config, self.install = config, install
        self.cancel = threading.Event()

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def run(self):
        from remote_ssh import SSHConnection
        connection = None
        try:
            connection = SSHConnection(self.config)
            result = connection.prepare(self.progress.emit, self.cancel, install=self.install,
                                        music=self.config.get('music_enabled', False))
            import requests
            with requests.Session() as session:
                session.trust_env = False
                session.get(connection.url + '/system_stats', timeout=15).raise_for_status()
            self.result.emit(True, tr('Drama 3 и музыка готовы. Можно сохранить серверный режим.') if self.config.get('music_enabled')
                             else tr('Drama 3 готова. Можно сохранить серверный режим.'))
        except Exception as exc:
            self.result.emit(False, str(exc))
        finally:
            if connection:
                connection.close()
            self.finished.emit()


class TTSSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Озвучка · компьютер или SSH-сервер'))
        self.setMinimumWidth(670)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.task = None
        self.verified = None
        self.closing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        title = QLabel(tr('Где создавать озвучку'))
        title.setObjectName('subtitle')
        layout.addWidget(title)
        self.mode = QComboBox()
        self.mode.addItem(tr('На этом компьютере · установленная модель'), 'local')
        self.mode.addItem('Drama 3 · SSH-сервер', 'remote')
        layout.addWidget(self.mode)
        self.panel = QFrame()
        form = QFormLayout(self.panel)
        form.setContentsMargins(0, 0, 0, 0)
        self.connection = QLineEdit()
        self.connection.setPlaceholderText('ssh root@gpu.example.org -p 2222')
        form.addRow(tr('SSH-подключение'), self.connection)
        row = QHBoxLayout()
        self.identity = QLineEdit()
        self.identity.setPlaceholderText(tr('Необязательно · иначе используется ssh-agent / ~/.ssh/config'))
        row.addWidget(self.identity, 1)
        self.browse = QPushButton(tr('Выбрать ключ'))
        self.browse.clicked.connect(self.choose_key)
        row.addWidget(self.browse)
        form.addRow(tr('Приватный ключ на этом ПК'), row)
        self.description = QLabel(tr('Linux · Python 3.12+ · NVIDIA 24 ГБ VRAM · 48–64 ГБ RAM · около 55 ГБ свободного SSD.\n'
            'Установим Drama 3 FP8, кодек и распознавание образца в отдельный каталог. Готовый совместимый сервер используем повторно. '
            'Сервер получает текст и голосовой образец; SSH-ключ остаётся на вашем ПК.'))
        self.description.setWordWrap(True)
        self.description.setObjectName('muted')
        form.addRow(self.description)
        self.music = QCheckBox(tr('Фоновая музыка'))
        self.music.setToolTip(tr('Stable Audio 3 Medium · дополнительно около 10,4 ГБ. Тихий фон под речь; исходная озвучка сохраняется.'))
        form.addRow(self.music)
        actions = QHBoxLayout()
        self.check_button = QPushButton(tr('Проверить подключение'))
        self.install_button = QPushButton(tr('Установить / запустить Drama 3'))
        self.check_button.clicked.connect(lambda: self.start_task(False))
        self.install_button.clicked.connect(lambda: self.start_task(True))
        actions.addWidget(self.check_button)
        actions.addWidget(self.install_button)
        form.addRow(actions)
        layout.addWidget(self.panel)
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setVisible(False)
        self.bar.setAccessibleName(tr('Прогресс настройки сервера'))
        layout.addWidget(self.bar)
        footer = QHBoxLayout()
        self.stop_button = QPushButton(tr('Остановить'))
        self.stop_button.clicked.connect(self.stop_task)
        self.stop_button.hide()
        footer.addWidget(self.stop_button)
        footer.addStretch()
        self.close_button = QPushButton(tr('Отмена'))
        self.close_button.clicked.connect(self.reject)
        footer.addWidget(self.close_button)
        self.save_button = QPushButton(tr('Сохранить'))
        self.save_button.setObjectName('primary')
        self.save_button.clicked.connect(self.save)
        footer.addWidget(self.save_button)
        layout.addLayout(footer)
        config = preferences.settings()
        self.connection.setText(config['connection'])
        self.identity.setText(config['identity_file'])
        self.music.setChecked(bool(config.get('music_enabled', False)))
        self.mode.setCurrentIndex(self.mode.findData(config['mode']))
        self.mode.currentIndexChanged.connect(self.refresh)
        self.connection.textChanged.connect(self.invalidate)
        self.identity.textChanged.connect(self.invalidate)
        self.music.toggled.connect(self.invalidate)
        self.refresh()

    def values(self):
        return dict(connection=self.connection.text().strip(), identity_file=self.identity.text().strip(),
                    music_enabled=self.music.isChecked())

    def invalidate(self):
        self.verified = None
        self.refresh()

    def refresh(self):
        remote = self.mode.currentData() == 'remote'
        self.panel.setVisible(remote)
        self.panel.setEnabled(self.task is None)
        self.mode.setEnabled(self.task is None)
        self.music.setEnabled(remote and self.task is None)
        self.install_button.setText(tr('Установить / запустить Drama 3 и музыку') if self.music.isChecked()
                                    else tr('Установить / запустить Drama 3'))
        self.save_button.setEnabled(self.task is None and (not remote or self.verified == self.values()))

    def choose_key(self):
        filename, _ = QFileDialog.getOpenFileName(self, tr('Выберите приватный SSH-ключ'))
        if filename:
            self.identity.setText(filename)

    def start_task(self, install):
        if self.task:
            return
        try:
            preferences.parse_connection(**dict(value=self.connection.text(), identity_file=self.identity.text()))
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        task = ServerTask(self.values(), install)
        self.task = task
        _tasks.add(task)
        task.progress.connect(self.on_progress)
        task.result.connect(self.on_result)
        task.finished.connect(self.on_finished)
        task.finished.connect(lambda t=task: (_tasks.discard(t), t.deleteLater()))
        self.bar.show()
        self.bar.setRange(0, 0)
        self.stop_button.show()
        self.stop_button.setEnabled(True)
        self.status.setText(tr('Подключаемся по SSH…'))
        self.refresh()
        task.start()

    @Slot(object)
    def on_progress(self, event):
        self.status.setText(event.get('message', ''))
        value = event.get('value')
        self.bar.setRange(0, 0 if value is None else 1000)
        if value is not None:
            self.bar.setValue(int(max(0, min(1, value))*1000))

    @Slot(bool, str)
    def on_result(self, success, message):
        self.status.setText(message)
        self.verified = self.values() if success else None
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000 if success else 0)

    @Slot()
    def on_finished(self):
        self.task = None
        self.stop_button.hide()
        self.refresh()
        if self.closing:
            super().reject()

    def stop_task(self):
        if self.task:
            self.task.cancel.set()
            self.stop_button.setEnabled(False)
            self.status.setText(tr('Отменяем текущий этап…'))

    def reject(self):
        if self.task:
            self.closing = True
            self.stop_task()
        else:
            super().reject()

    def save(self):
        if not self.save_button.isEnabled():
            return
        try:
            preferences.save(self.mode.currentData(), **self.values())
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.accept()
