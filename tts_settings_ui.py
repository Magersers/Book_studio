"""RouterAI speech and optional local music/SFX setup with cancellable progress."""
import json
import threading

from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton, QProgressBar, QFrame, QCheckBox, QPlainTextEdit, QGroupBox,
    QScrollArea, QWidget, QComboBox)

from ui_language import tr
import tts_settings as preferences

_tasks = set()


class SetupTask(QObject):
    progress = Signal(object)
    result = Signal(bool, str)
    finished = Signal()

    def __init__(self, operation, base_url='', key='', model=preferences.DEFAULT_MODEL):
        super().__init__()
        self.operation, self.base_url, self.key, self.model = operation, base_url, key, model
        self.cancel = threading.Event()

    def start(self):
        threading.Thread(target=self.run, daemon=True).start()

    def check_cancel(self):
        if self.cancel.is_set():
            raise RuntimeError(tr('Настройка отменена.'))

    def run(self):
        try:
            self.check_cancel()
            if self.operation == 'api':
                from routerai_engine import probe
                message = probe(self.base_url, self.key, self.model, cancel=self.cancel)
                self.check_cancel()
            else:
                from local_audio_runtime import prepare
                prepare(progress=lambda value, message: self.progress.emit(dict(value=value, message=message)),
                        cancel=self.check_cancel)
                self.check_cancel()
                message = tr('Музыка и звуки готовы к локальной генерации.')
            self.result.emit(True, str(message))
        except Exception as exc:
            message = str(exc)
            if self.key:
                message = message.replace(self.key, '[скрыто]')
            self.result.emit(False, message)
        finally:
            self.key = ''
            self.finished.emit()


class TTSSettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr('Озвучка · RouterAI и локальный звук'))
        self.setMinimumWidth(680)
        self.resize(720, 760)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.task = None
        self.closing = False
        config = preferences.settings()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumHeight(380)
        body = QWidget()
        fields = QVBoxLayout(body)
        fields.setContentsMargins(0, 0, 6, 0)
        fields.setSpacing(14)
        scroll.setWidget(body)
        layout.addWidget(scroll, 1)
        title = QLabel(tr('Голоса · Drama 3 через RouterAI'))
        title.setObjectName('subtitle')
        fields.addWidget(title)
        self.panel = QFrame()
        form = QFormLayout(self.panel)
        form.setContentsMargins(0, 0, 0, 0)
        self.url = QLineEdit(config['base_url'])
        self.url.setReadOnly(True)
        form.addRow(tr('Адрес API'), self.url)
        self.model = QLineEdit(preferences.DEFAULT_MODEL)
        self.model.setReadOnly(True)
        form.addRow(tr('Модель'), self.model)
        row = QHBoxLayout()
        self.key = QLineEdit()
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        self.key.setClearButtonEnabled(True)
        self.key.setPlaceholderText(tr('Ключ сохранён · оставьте пустым, чтобы сохранить его')
                                   if config['has_key'] else tr('Вставьте API-ключ RouterAI'))
        row.addWidget(self.key, 1)
        self.show_key = QPushButton(tr('Показать'))
        self.show_key.setCheckable(True)
        self.show_key.toggled.connect(lambda visible: self.key.setEchoMode(
            QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password))
        row.addWidget(self.show_key)
        form.addRow(tr('API-ключ'), row)
        link = QLabel('<a href="https://routerai.ru/">RouterAI ↗</a>')
        link.setOpenExternalLinks(True)
        form.addRow('', link)
        description = QLabel(tr('Речь создаётся через API: текст и ID выбранного голоса отправляются RouterAI. '
            'Используйте голоса из каталога Fish Audio или укажите ID своего созданного голоса. '
            'Эмоции задаются тегами в тексте. '
            'API-ключ хранится зашифрованным для вашей учётной записи Windows.'))
        description.setWordWrap(True)
        description.setObjectName('muted')
        form.addRow(description)
        self.check_button = QPushButton(tr('Проверить API-ключ'))
        self.check_button.setToolTip(tr('Проверяет доступ к модели без платной генерации речи.'))
        self.check_button.clicked.connect(self.start_api_check)
        form.addRow('', self.check_button)
        advanced = QGroupBox(tr('Дополнительные параметры Fish Audio · JSON'))
        advanced_form = QVBoxLayout(advanced)
        self.fish_options = QPlainTextEdit(json.dumps(config.get('fish_options', {}), ensure_ascii=False, indent=2))
        self.fish_options.setMaximumHeight(100)
        self.fish_options.setPlaceholderText('{"temperature": 1.0, "top_p": 0.9}')
        self.fish_options.setToolTip(tr('Необязательные параметры Fish Audio. ID голоса и формат задаёт программа. '
                                      'Поддержка дополнительных параметров зависит от RouterAI.'))
        advanced_form.addWidget(self.fish_options)
        form.addRow(advanced)
        fields.addWidget(self.panel)
        self.audio_panel = QFrame()
        audio = QVBoxLayout(self.audio_panel)
        audio.setContentsMargins(0, 0, 0, 0)
        audio_title = QLabel(tr('Музыка и звуки · на этом компьютере'))
        audio_title.setObjectName('subtitle')
        audio.addWidget(audio_title)
        self.music = QCheckBox(tr('Фоновая музыка'))
        self.music.setChecked(config.get('music_enabled', False))
        self.music.setToolTip(tr('Тихий фон под речь. Исходная озвучка сохраняется отдельно.'))
        audio.addWidget(self.music)
        self.sounds = QCheckBox(tr('Генерировать звуковые эффекты'))
        self.sounds.setChecked(config.get('sound_generation_enabled', False))
        self.sounds.setToolTip(tr('Скрип двери, шаги и другие эффекты из разметки книги.'))
        audio.addWidget(self.sounds)
        local_description = QLabel(tr('Одна Stable Audio 3 Medium используется для музыки и эффектов. '
            'Модели занимают около 10,4 ГБ на диске; окружение устанавливается отдельно. '
            'Для 8 ГБ видеопамяти используются короткие блоки и выгрузка в оперативную память. '
            'Загрузка начнётся при первой генерации или по кнопке ниже.'))
        local_description.setWordWrap(True)
        local_description.setObjectName('muted')
        audio.addWidget(local_description)
        device_row = QHBoxLayout()
        device_row.addWidget(QLabel(tr('Устройство для музыки и звуков')))
        self.device = QComboBox()
        self.device.addItem(tr('NVIDIA · GPU + оперативная память'), 'auto')
        self.device.addItem(tr('CPU · медленнее'), 'cpu')
        self.device.setCurrentIndex(1 if config.get('local_audio_device') == 'cpu' else 0)
        device_row.addWidget(self.device, 1)
        audio.addLayout(device_row)
        self.install_button = QPushButton(tr('Подготовить музыку и звуки'))
        self.install_button.clicked.connect(self.start_audio_setup)
        audio.addWidget(self.install_button)
        fields.addWidget(self.audio_panel)
        fields.addStretch()
        self.status = QLabel('')
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.hide()
        self.bar.setAccessibleName(tr('Прогресс настройки озвучки'))
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

    def values(self):
        return dict(base_url=preferences.normalize_url(self.url.text()),
                    model=preferences.validate_model(self.model.text()),
                    music_enabled=self.music.isChecked(),
                    sound_generation_enabled=self.sounds.isChecked(),
                    local_audio_device=self.device.currentData(),
                    fish_options=preferences.validate_fish_options(self.fish_options.toPlainText()))

    def refresh(self):
        busy = self.task is not None
        self.panel.setEnabled(not busy)
        self.audio_panel.setEnabled(not busy)
        self.save_button.setEnabled(not busy)

    def launch(self, task, message):
        if self.task:
            return
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
        self.status.setText(message)
        self.refresh()
        task.start()

    def start_api_check(self):
        if self.task:
            return
        try:
            values = self.values()
            key = preferences.validate_key(self.key.text()) if self.key.text().strip() else preferences.api_key(values['base_url'])
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.launch(SetupTask('api', values['base_url'], key, values['model']),
                    tr('Проверяем ключ и доступность Drama 3…'))

    def start_audio_setup(self):
        if not self.task:
            self.launch(SetupTask('audio'), tr('Подготавливаем локальную модель музыки и звуков…'))

    @Slot(object)
    def on_progress(self, event):
        self.status.setText(event.get('message', ''))
        value = event.get('value')
        self.bar.setRange(0, 0 if value is None else 1000)
        if value is not None:
            self.bar.setValue(int(max(0, min(1, value)) * 1000))

    @Slot(bool, str)
    def on_result(self, success, message):
        self.status.setText(message)
        self.bar.setRange(0, 1000)
        self.bar.setValue(1000 if success else 0)

    @Slot()
    def on_finished(self):
        self.task = None
        self.stop_button.hide()
        self.refresh()
        if self.closing:
            self.key.clear()
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
            self.key.clear()
            super().reject()

    def save(self):
        if self.task:
            return
        try:
            preferences.save('api', key=self.key.text(), **self.values())
        except Exception as exc:
            self.status.setText(str(exc))
            return
        self.key.clear()
        self.accept()
