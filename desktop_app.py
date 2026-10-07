"""Vox Studio: native desktop UI, durable voice avatars, owned GPU worker."""
from ui_language import tr
import ctypes
import hashlib
import json
import math
import os
import shutil
import sys
from pathlib import Path

os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')
from PySide6.QtCore import Qt, QTimer, Signal, QObject, QProcess, QProcessEnvironment, QSize, QUrl, QLockFile
from PySide6.QtGui import QColor, QFont, QPainter, QLinearGradient, QDesktopServices, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QFrame, QLabel, QPushButton, QHBoxLayout,
    QVBoxLayout, QStackedWidget, QProgressBar, QListWidget, QListWidgetItem, QTextEdit, QSpinBox,
    QDoubleSpinBox, QSlider, QComboBox, QDialog, QLineEdit, QFileDialog, QMessageBox, QFormLayout)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtNetwork import QLocalServer, QLocalSocket
import avatar_store as store
from desktop_job import WorkerJob
from desktop_assets import logo, profile_icon, ensure_assets

ROOT = Path(__file__).resolve().parent
STYLE = '''
QWidget { background:#101218; color:#efedf9; font-family:"Segoe UI"; font-size:13px; }
QMainWindow { background:#101218; }
QLabel { background:transparent; }
QFrame#sidebar { background:#151922; border-right:1px solid #2c303d; }
QFrame#panel { background:#191c25; border:1px solid #2c303d; border-radius:14px; }
QFrame#panel QLabel, QFrame#sidebar QLabel { background:transparent; }
QLabel#muted { color:#999bb4; }
QLabel#eyebrow { color:#aaa0db; font-size:11px; font-weight:600; }
QLabel#title { font-size:28px; font-weight:600; letter-spacing:-.5px; }
QLabel#subtitle { font-size:20px; font-weight:600; }
QLabel#badge { color:#8ce1ce; background:#1c3435; border-radius:11px; padding:5px 11px; font-size:11px; }
QPushButton { background:#242936; border:1px solid #353c4b; border-radius:8px; padding:10px 15px; font-weight:600; }
QPushButton:hover { background:#323348; border-color:#70648f; }
QPushButton:pressed { background:#3b3552; }
QPushButton:disabled { color:#77798e; background:#20212e; border-color:#292a3a; }
QPushButton#primary { color:#191429; background:#b4a0f5; border:1px solid #c8b9fc; padding:12px 22px; }
QPushButton#primary:hover { background:#ccbcff; }
QPushButton#primary:disabled { color:#b2a8ca; background:#493960; border-color:#594776; }
QPushButton#quiet { background:transparent; border:0; color:#b8b2d4; padding:7px; }
QPushButton#play { background:#8562ee; color:white; border:0; border-radius:22px; font-size:18px; }
QListWidget { background:transparent; border:0; outline:0; padding:3px; }
QListWidget::item { border:1px solid transparent; border-radius:13px; padding:11px 8px; margin:3px 0; }
QListWidget::item:selected { background:#353049; border:1px solid #706090; }
QListWidget::item { color:#efedf9; }
QComboBox { background:#20212f; color:#efedf9; border:1px solid #393a51; border-radius:8px; padding:7px; }
QComboBox QAbstractItemView { background:#242536; color:#efedf9; selection-background-color:#655094; }
QTableWidget { background:#141520; gridline-color:#2b2c40; selection-background-color:#51416d; selection-color:#ffffff; }
QHeaderView::section { background:#242536; color:#ddd8ed; border:0; padding:7px; }
QListWidget::item:hover:!selected { background:#252636; }
QTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox { background:#141520; border:1px solid #36374c; border-radius:11px; padding:11px; selection-background-color:#655094; }
QTextEdit:focus, QLineEdit:focus { border-color:#9576ef; }
QSpinBox, QDoubleSpinBox { padding:7px; min-height:22px; }
QProgressBar { background:#262739; border:0; border-radius:4px; min-height:6px; max-height:6px; color:transparent; }
QProgressBar::chunk { background:#9876fa; border-radius:4px; }
QSlider::groove:horizontal { height:4px; background:#36374c; border-radius:2px; }
QSlider::sub-page:horizontal { background:#ac8aff; border-radius:2px; }
QSlider::handle:horizontal { background:#e4d7ff; width:12px; margin:-4px 0; border-radius:6px; }
QScrollBar:vertical { background:transparent; width:7px; margin:0; }
QScrollBar::handle:vertical { background:#44445e; border-radius:3px; min-height:24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QDialog { background:#191a26; }
QToolTip { color:#eee; background:#282639; border:1px solid #555; }
QMenu {background:#1b202b;color:#eceaf4;border:1px solid #394052;padding:5px;}
QMenu::item {padding:8px 24px;border-radius:5px;}
QMenu::item:selected {background:#3e3455;}
QMenu::item:disabled {color:#737d90;}
QMenu::separator {height:1px;background:#363d4b;margin:5px 8px;}
'''


def label(text, kind=''):
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    return widget


def button(text, kind=''):
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        widget.setObjectName(kind)
    return widget


def duration_text(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds//60}:{seconds%60:02d}'


class Wave(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedSize(360, 110)
        self.phase = 0.
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(35)

    def animate(self):
        self.phase += .11
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(31):
            envelope = math.sin(math.pi * (index+1)/32)
            height = 8 + envelope * (22 + 50 * (.5+.5*math.sin(self.phase+index*.47)))
            gradient = QLinearGradient(0, 0, 0, 110)
            gradient.setColorAt(0, QColor('#c4afff'))
            gradient.setColorAt(1, QColor('#6852bb'))
            painter.setBrush(gradient)
            painter.drawRoundedRect(12+index*11, int((110-height)/2), 5, int(height), 2.5, 2.5)


class Backend(QObject):
    event = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        self.process.readyReadStandardOutput.connect(self.read_stdout)
        self.process.readyReadStandardError.connect(self.read_stderr)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.buffer = b''
        self.job = None
        self.log = None
        self.stopping = False
        self.worker_pid = None
        self.failed = False

    def start(self):
        try:
            self.job = WorkerJob()
            (ROOT / 'logs').mkdir(exist_ok=True)
            self.log = (ROOT / 'logs/desktop-worker.log').open('ab', buffering=0)
            self.log.write(b'\n--- Desktop worker starting ---\n')
            environment = QProcessEnvironment.systemEnvironment()
            for key, value in dict(PYTHONUTF8='1', PYTHONUNBUFFERED='1', OMP_NUM_THREADS='6',
                                   MKL_NUM_THREADS='6', VOX_JOB_NAME=self.job.name).items():
                environment.insert(key, value)
            self.process.setProcessEnvironment(environment)
            self.process.setWorkingDirectory(str(ROOT))
            self.process.start(str(ROOT / '.venv/Scripts/python.exe'), ['-X', 'utf8', '-u', str(ROOT / 'desktop_worker.py')])
        except Exception as exc:
            self.event.emit(dict(type='fatal', message=str(exc)))

    def read_stdout(self):
        self.buffer += bytes(self.process.readAllStandardOutput())
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
                if event.get('type') == 'hello':
                    self.worker_pid = event['pid']
                if event.get('type') == 'fatal':
                    self.failed = True
                self.event.emit(event)
            except (ValueError, UnicodeDecodeError):
                if self.log:
                    self.log.write(line+b'\n')

    def read_stderr(self):
        content = bytes(self.process.readAllStandardError())
        if self.log:
            self.log.write(content)

    def send(self, command):
        if self.process.state() != QProcess.ProcessState.Running:
            self.event.emit(dict(type='fatal', message=tr('Голосовой движок не запущен. Повторите запуск.')))
            return
        self.process.write((json.dumps(command, ensure_ascii=False)+'\n').encode('utf-8'))

    def process_error(self, error):
        if not self.stopping and error == QProcess.ProcessError.FailedToStart:
            self.event.emit(dict(type='fatal', message=tr('Не удалось запустить Python. Проверьте окружение .venv.')))

    def finished(self, *args):
        if not self.stopping and not self.failed:
            self.event.emit(dict(type='fatal', message=tr('Голосовой движок остановился. Нажмите «Повторить запуск».')))

    def stop(self):
        self.stopping = True
        if self.job:
            self.job.close()
        if self.process.state() != QProcess.ProcessState.NotRunning:
            self.process.kill()
            self.process.waitForFinished(1500)
        self.read_stderr()
        if self.log:
            self.log.close()
            self.log = None


class AvatarDialog(QDialog):
    def __init__(self, parent, avatar=None, initial=None):
        super().__init__(parent)
        self.avatar = avatar
        self.picture = ''
        self.setWindowTitle(tr('Редактировать аватар') if avatar else tr('Новый голосовой аватар'))
        self.setMinimumWidth(590)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 25, 28, 25)
        layout.setSpacing(16)
        layout.addWidget(label(tr('Знакомьтесь, ваш новый голос') if not avatar else tr('Настройки аватара'), 'subtitle'))
        hint = label(tr('Сохраните образец один раз — и используйте голос в любых текстах.'), 'muted')
        hint.setWordWrap(True)
        layout.addWidget(hint)
        identity = QHBoxLayout()
        self.portrait = QLabel()
        self.portrait.setFixedSize(68, 68)
        identity.addWidget(self.portrait)
        self.name = QLineEdit(avatar['name'] if avatar else '')
        self.name.setPlaceholderText(tr('Имя аватара'))
        self.name.setMaxLength(60)
        identity.addWidget(self.name, 1)
        photo = button(tr('Картинка'))
        photo.clicked.connect(self.choose_picture)
        identity.addWidget(photo)
        layout.addLayout(identity)
        self.name.textChanged.connect(self.update_portrait)
        row = QHBoxLayout()
        self.reference = QLineEdit(str(store.avatar_path(avatar)) if avatar else '')
        self.reference.setReadOnly(True)
        self.reference.setPlaceholderText('MP3, WAV, M4A, FLAC…')
        row.addWidget(self.reference, 1)
        choose = button(tr('Выбрать голос'))
        choose.clicked.connect(self.choose_reference)
        row.addWidget(choose)
        layout.addLayout(row)
        microphone = button(tr('●  Записать с микрофона'))
        microphone.clicked.connect(self.record_voice)
        layout.addWidget(microphone)
        controls = QHBoxLayout()
        self.start = QDoubleSpinBox()
        self.start.setRange(0, 36000)
        self.start.setSuffix(tr(' с'))
        self.length = QDoubleSpinBox()
        self.length.setRange(3, 30)
        self.length.setValue(avatar['duration'] if avatar else 15)
        self.length.setSuffix(tr(' с'))
        controls.addWidget(label(tr('Начало фрагмента'), 'muted'))
        controls.addWidget(self.start)
        controls.addSpacing(15)
        controls.addWidget(label(tr('Длительность'), 'muted'))
        controls.addWidget(self.length)
        layout.addLayout(controls)
        layout.addWidget(label(tr('Слова в выбранном образце'), 'eyebrow'))
        self.transcript = QTextEdit()
        self.transcript.setFixedHeight(130)
        self.transcript.setPlaceholderText(tr('Оставьте пустым для автоматического распознавания.\nТочная расшифровка помогает сохранить сходство голоса.'))
        self.transcript.setPlainText(avatar['transcript'] if avatar else '')
        layout.addWidget(self.transcript)
        self.start.valueChanged.connect(self.clear_transcript)
        self.length.valueChanged.connect(self.clear_transcript)
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = button(tr('Отмена'))
        cancel.clicked.connect(self.reject)
        save = button(tr('Сохранить аватар'), 'primary')
        save.clicked.connect(self.validate)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addLayout(footer)
        if initial:
            self.name.setText(initial['name'])
            self.reference.setText(initial['reference'])
            self.start.setValue(initial['start'])
            self.length.setValue(initial['duration'])
            self.transcript.setPlainText(initial['transcript'])
            self.picture = initial.get('picture', '')
        self.update_portrait()

    def clear_transcript(self, *args):
        self.transcript.clear()

    def update_portrait(self, *args):
        picture = self.picture or (str(store.avatar_path(self.avatar, 'portrait.png')) if self.avatar else '')
        self.portrait.setPixmap(profile_icon(self.name.text() or tr('Голос'), picture, 68))

    def choose_picture(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Картинка аватара'), '', tr('Изображения (*.png *.jpg *.jpeg *.webp *.bmp)'))
        if path:
            self.picture = path
            self.update_portrait()

    def choose_reference(self):
        path, _ = QFileDialog.getOpenFileName(self, tr('Образец голоса'), '', tr('Аудио (*.mp3 *.wav *.m4a *.flac *.ogg *.aac);;Все файлы (*)'))
        if path:
            self.reference.setText(path)
            self.start.setValue(0)
            self.transcript.clear()

    def record_voice(self):
        from microphone_ui import RecordDialog
        dialog = RecordDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.path:
            self.reference.setText(dialog.path)
            self.start.setValue(0)
            self.length.setValue(min(30, dialog.duration))
            self.transcript.clear()

    def validate(self):
        if not self.name.text().strip() or not Path(self.reference.text()).is_file():
            QMessageBox.information(self, tr('Немного не хватает'), tr('Укажите имя аватара и выберите файл с голосом.'))
            return
        self.accept()

    def payload(self):
        return dict(action='save_avatar', name=self.name.text().strip(), reference=self.reference.text(),
                    transcript=self.transcript.toPlainText().strip(), start=self.start.value(),
                    duration=self.length.value(), picture=self.picture,
                    avatar_id=self.avatar['id'] if self.avatar else None)


class MainWindow(QMainWindow):
    def __init__(self, start_backend=True):
        super().__init__()
        self.setWindowTitle('Vox Studio')
        self.setWindowIcon(ensure_assets())
        self.setMinimumSize(1000, 640)
        screen = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1190, screen.width()-60), min(820, screen.height()-60))
        self.backend = None
        self.ready = False
        self.busy = False
        self.closing = False
        self.current_avatar = None
        self.current_record = None
        self.pending_avatar = None
        self.book_dialog = None
        self.settings = store.load_json(store.DATA / 'settings.json', {})
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(.8)
        self.player.setAudioOutput(self.audio)
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.build_loading()
        self.build_studio()
        self.refresh_avatars(self.settings.get('avatar_id'))
        self.refresh_history()
        from desktop_menus import install
        install(self)
        if start_backend:
            QTimer.singleShot(120, self.start_backend)

    def showEvent(self, event):
        super().showEvent(event)
        if os.name == 'nt':
            try:
                value = ctypes.c_int(1)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 20, ctypes.byref(value), 4)
            except Exception:
                pass

    def build_loading(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)
        mark = QLabel()
        mark.setPixmap(logo(76))
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(mark)
        name = label('Vox Studio', 'title')
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)
        slogan = label(tr('У каждого текста есть свой голос.'), 'muted')
        slogan.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(slogan)
        self.wave = Wave()
        layout.addWidget(self.wave, 0, Qt.AlignmentFlag.AlignHCenter)
        self.loading_status = label(tr('Открываем вашу студию…'), 'muted')
        self.loading_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_status.setWordWrap(True)
        layout.addWidget(self.loading_status)
        self.loading_bar = QProgressBar()
        self.loading_bar.setRange(0, 0)
        self.loading_bar.setFixedWidth(390)
        layout.addWidget(self.loading_bar, 0, Qt.AlignmentFlag.AlignHCenter)
        self.retry = button(tr('Повторить запуск'), 'primary')
        self.retry.clicked.connect(self.start_backend)
        self.retry.hide()
        layout.addWidget(self.retry, 0, Qt.AlignmentFlag.AlignHCenter)
        caption = label(tr('Локальная озвучка · Личная библиотека голосов'), 'eyebrow')
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)
        self.stack.addWidget(page)

    def build_studio(self):
        page = QWidget()
        outer = QHBoxLayout(page)
        outer.setContentsMargins(0,0,0,0)
        outer.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(265)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(19, 24, 19, 20)
        side.setSpacing(14)
        brand = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(logo(39))
        brand.addWidget(icon)
        brand.addWidget(label('Vox Studio', 'subtitle'))
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(18)
        side.addWidget(label(tr('ВАША БИБЛИОТЕКА'), 'eyebrow'))
        from avatar_tree import AvatarTree
        self.avatar_list = AvatarTree(self)
        self.avatar_search=QLineEdit()
        self.avatar_search.setPlaceholderText(tr('Поиск аватара или папки…'))
        self.avatar_search.setClearButtonEnabled(True)
        self.avatar_search.textChanged.connect(self.avatar_list.set_filter)
        side.addWidget(self.avatar_search)
        self.avatar_list.setIconSize(QSize(43, 43))
        self.avatar_list.currentItemChanged.connect(self.select_avatar)
        side.addWidget(self.avatar_list, 1)
        self.folder_button = button(tr('+  Новая папка'), 'quiet')
        self.folder_button.clicked.connect(lambda: self.avatar_list.new_folder())
        side.addWidget(self.folder_button)
        self.add_button = button(tr('+  Новый аватар'), 'primary')
        self.add_button.clicked.connect(lambda: self.edit_avatar(False))
        side.addWidget(self.add_button)
        self.edit_button = button(tr('Настроить аватар'), 'quiet')
        self.edit_button.clicked.connect(lambda: self.edit_avatar(True))
        side.addWidget(self.edit_button)
        self.archive_button = button(tr('Убрать из библиотеки'), 'quiet')
        self.archive_button.clicked.connect(self.archive_avatar)
        side.addWidget(self.archive_button)
        self.books_button = button(tr('▤  Аудиокниги'))
        self.books_button.clicked.connect(self.open_books)
        side.addWidget(self.books_button)
        self.analysis_settings_button = button(tr('Модель разметки / API'))
        self.analysis_settings_button.clicked.connect(self.configure_analysis)
        side.addWidget(self.analysis_settings_button)
        from ui_language import language, save_language
        self.language_choice = QComboBox()
        self.language_choice.addItem('Русский', 'ru'); self.language_choice.addItem('English', 'en')
        self.language_choice.setCurrentIndex(1 if language() == 'en' else 0)
        self.language_choice.setToolTip(tr('Язык интерфейса'))
        def change_language():
            save_language(self.language_choice.currentData())
            QMessageBox.information(self, 'Language / Язык', 'Restart the application to apply the language.\nПерезапустите программу для смены языка.')
        self.language_choice.activated.connect(change_language)
        side.addWidget(self.language_choice)
        side.addSpacing(10)
        self.analysis_provider_label = label('', 'muted')
        self.analysis_provider_label.setWordWrap(True)
        self.analysis_provider_label.setStyleSheet('font-size:11px;color:#9294ab;')
        side.addWidget(self.analysis_provider_label)
        self.refresh_analysis_provider()
        outer.addWidget(sidebar)
        body = QVBoxLayout()
        body.setContentsMargins(28, 24, 28, 20)
        body.setSpacing(16)
        heading = QHBoxLayout()
        headings = QVBoxLayout()
        headings.setSpacing(5)
        headings.addWidget(label(tr('СТУДИЯ ОЗВУЧКИ'), 'eyebrow'))
        headings.addWidget(label(tr('Пусть ваш текст заговорит.'), 'title'))
        heading.addLayout(headings, 1)
        self.badge = label(tr('●  Готов к работе'), 'badge')
        heading.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignTop)
        body.addLayout(heading)
        selected = QHBoxLayout()
        self.selected_icon = QLabel()
        self.selected_icon.setFixedSize(43,43)
        selected.addWidget(self.selected_icon)
        self.selected_name = label(tr('Выберите или создайте аватар'), 'subtitle')
        selected.addWidget(self.selected_name, 1)
        self.preview_button = button(tr('▷  Образец'), 'quiet')
        self.preview_button.clicked.connect(self.preview_reference)
        selected.addWidget(self.preview_button)
        body.addLayout(selected)
        editor_panel = QFrame()
        editor_panel.setObjectName('panel')
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(18, 15, 18, 15)
        row = QHBoxLayout()
        row.addWidget(label(tr('Текст для озвучки'), 'eyebrow'))
        row.addStretch()
        paste = button(tr('Вставить'), 'quiet')
        paste.clicked.connect(lambda: self.editor.insertPlainText(QApplication.clipboard().text()))
        row.addWidget(paste)
        editor_layout.addLayout(row)
        self.editor = QTextEdit()
        self.editor.setPlaceholderText(tr('Напишите историю, реплику или мысль.\nАватар произнесёт её вашим голосом…'))
        self.editor.setMinimumHeight(120)
        self.editor.setStyleSheet('QTextEdit {background:transparent;border:0;padding:3px;font-size:16px;}')
        self.editor.setPlainText(self.settings.get('draft', ''))
        self.editor.textChanged.connect(self.update_controls)
        editor_layout.addWidget(self.editor, 1)
        editor_footer = QHBoxLayout()
        self.char_count = label('0 / 3000', 'muted')
        self.char_count.setStyleSheet('color:#9395ad;font-size:11px;')
        editor_footer.addWidget(self.char_count)
        editor_footer.addStretch()
        editor_footer.addWidget(label(tr('Вариация'), 'muted'))
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setValue(int(self.settings.get('seed', 42)))
        self.seed.setFixedWidth(103)
        self.seed.setToolTip(tr('Другое число создаёт другую вариацию интонации.'))
        editor_footer.addWidget(self.seed)
        editor_footer.addSpacing(8)
        self.generate_button = button(tr('✦  Озвучить текст'), 'primary')
        self.generate_button.clicked.connect(self.generate)
        editor_footer.addWidget(self.generate_button)
        editor_layout.addLayout(editor_footer)
        body.addWidget(editor_panel, 1)
        status = QHBoxLayout()
        self.status_text = label(tr('Выберите голос и добавьте текст.'), 'muted')
        self.status_text.setWordWrap(True)
        status.addWidget(self.status_text, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0,1000)
        self.progress.setFixedWidth(155)
        self.progress.hide()
        status.addWidget(self.progress)
        body.addLayout(status)
        history_header = QHBoxLayout()
        history_header.addWidget(label(tr('Последние записи'), 'subtitle'))
        history_header.addStretch()
        folder = button(tr('Открыть папку ↗'), 'quiet')
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(ROOT / 'outputs'))))
        history_header.addWidget(folder)
        body.addLayout(history_header)
        self.history_list = QListWidget()
        self.history_list.setFixedHeight(124)
        self.history_list.currentItemChanged.connect(self.select_record)
        body.addWidget(self.history_list)
        self.player_panel = QFrame()
        self.player_panel.setObjectName('panel')
        playback = QHBoxLayout(self.player_panel)
        playback.setContentsMargins(16,12,16,12)
        playback.setSpacing(13)
        self.play = button('▶', 'play')
        self.play.setFixedSize(44,44)
        self.play.clicked.connect(self.toggle_play)
        playback.addWidget(self.play)
        player_center = QVBoxLayout()
        self.track_name = label(tr('Ваша следующая запись появится здесь'), 'muted')
        self.track_name.setMaximumWidth(430)
        player_center.addWidget(self.track_name)
        seek_row = QHBoxLayout()
        self.seek = QSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0,0)
        self.seek.sliderMoved.connect(self.player.setPosition)
        seek_row.addWidget(self.seek, 1)
        self.time = label('0:00 / 0:00', 'muted')
        self.time.setStyleSheet('font-size:11px;color:#999bb4;')
        seek_row.addWidget(self.time)
        player_center.addLayout(seek_row)
        playback.addLayout(player_center, 1)
        self.export_mp3 = button('MP3 ↓')
        self.export_mp3.clicked.connect(lambda: self.export('mp3'))
        self.export_wav = button('WAV ↓')
        self.export_wav.clicked.connect(lambda: self.export('wav'))
        playback.addWidget(self.export_mp3)
        playback.addWidget(self.export_wav)
        body.addWidget(self.player_panel)
        outer.addLayout(body, 1)
        self.stack.addWidget(page)
        self.player.positionChanged.connect(self.update_playback)
        self.player.durationChanged.connect(self.update_playback)
        self.player.playbackStateChanged.connect(lambda state: self.play.setText('❚❚' if state == QMediaPlayer.PlaybackState.PlayingState else '▶'))
        self.player.errorOccurred.connect(lambda error, text: self.status_text.setText(tr('Не удалось воспроизвести файл: ') + text))

    def start_backend(self):
        if self.backend:
            self.backend.stop()
            self.backend.deleteLater()
        self.ready = False
        self.busy = False
        self.stack.setCurrentIndex(0)
        self.retry.hide()
        self.loading_bar.show()
        self.loading_status.setText(tr('Открываем вашу студию…'))
        self.wave.timer.start(35)
        self.backend = Backend(self)
        self.backend.event.connect(self.on_event)
        self.backend.start()

    def on_event(self, event):
        kind = event.get('type')
        if self.book_dialog and (self.book_dialog.running or kind.startswith('book_') or kind=='models_unloaded'):
            self.book_dialog.handle(event)
        if kind=='book_state':
            return
        if kind.startswith('book_'):
            self.set_busy(False)
            self.status_text.setText(event.get('message', tr('Книга на паузе. Готовые фрагменты сохранены.')))
            return
        if kind == 'progress':
            message = event['message'].replace('Qwen-TTS:', tr('Озвучиваем:'))
            self.loading_status.setText(message)
            self.status_text.setText(message)
            self.progress.setValue(int(event.get('value', 0)*1000))
        elif kind == 'ready':
            self.wave.timer.stop()
            self.ready = True
            self.stack.setCurrentIndex(1)
            self.status_text.setText(tr('Студия готова. Выберите голос и добавьте текст.'))
            self.update_controls()
        elif kind == 'avatar_saved':
            self.pending_avatar = None
            self.set_busy(False)
            self.refresh_avatars(event['avatar']['id'])
            self.status_text.setText(tr('Аватар сохранён. Его голос доступен после перезапуска приложения.'))
        elif kind == 'generated':
            self.set_busy(False)
            self.refresh_history(event['entry']['id'])
            self.status_text.setText(tr('Готово! Прослушайте запись или сохраните её в MP3 / WAV.'))
            if event['entry'].get('missing_text'):
                missing=event['entry']['missing_text']
                self.status_text.setText((tr('Озвучка завершена с пропусками: ') + f'{len(missing)}' + tr('. Остальной текст сохранён.')))
                QMessageBox.warning(self,tr('Есть неозвученные реплики'),tr('Остальной текст озвучен. Не удалось озвучить:\n\n')+'\n'.join(missing))
            elif event['entry'].get('needs_review'):self.status_text.setText(tr('Запись требует проверки — прослушайте её перед экспортом.'))
        elif kind in ('error', 'fatal'):
            self.set_busy(False)
            if kind == 'fatal':
                self.ready = False
                self.stack.setCurrentIndex(0)
                self.loading_bar.hide()
                self.loading_status.setText(event.get('message', tr('Не удалось запустить модель.')))
                self.retry.show()
            else:
                self.status_text.setText(tr('Не удалось выполнить действие. Все сохранённые аватары на месте.'))
                QMessageBox.warning(self, tr('Не получилось'), event.get('message', tr('Неизвестная ошибка.')))
            self.update_controls()

    def refresh_avatars(self, selected=None):
        self.avatar_list.reload(selected,lambda avatar:profile_icon(avatar['name'], str(store.avatar_path(avatar, 'portrait.png')), 64))
        self.select_avatar(self.avatar_list.currentItem())

    def select_avatar(self, current, previous=None):
        self.current_avatar = current.data(0, Qt.ItemDataRole.UserRole) if current else None
        if self.current_avatar:
            item = self.current_avatar
            self.selected_name.setText(item['name'])
            self.selected_icon.setPixmap(profile_icon(item['name'], str(store.avatar_path(item, 'portrait.png')), 43))
        else:
            self.selected_name.setText(tr('Выберите аватар в папке') if store.avatars() else tr('Создайте свой первый голос'))
            self.selected_icon.setPixmap(logo(43))
        self.update_controls()

    def update_controls(self):
        if not hasattr(self, 'generate_button'):
            return
        count = len(self.editor.toPlainText())
        self.char_count.setText(f'{count} / 3000')
        self.char_count.setStyleSheet('font-size:11px;color:'+('#ef9fa5' if count > 3000 else '#9395ad')+';')
        self.generate_button.setEnabled(self.ready and not self.busy and self.current_avatar is not None and 0 < count <= 3000)
        self.generate_button.setText(tr('Создаём запись…') if self.busy else tr('✦  Озвучить текст'))
        self.add_button.setEnabled(self.ready and not self.busy)
        self.edit_button.setEnabled(self.ready and not self.busy and self.current_avatar is not None)
        self.archive_button.setEnabled(self.ready and not self.busy and self.current_avatar is not None)
        self.books_button.setEnabled(self.ready and not self.busy)
        self.analysis_settings_button.setEnabled(not self.busy)
        self.preview_button.setEnabled(self.current_avatar is not None)
        self.play.setEnabled(not self.player.source().isEmpty())
        self.export_mp3.setEnabled(self.current_record is not None)
        self.export_wav.setEnabled(self.current_record is not None)

    def set_busy(self, value):
        self.busy = value
        self.badge.setText(tr('●  Создаём запись') if value else tr('●  Готов к работе'))
        self.progress.setVisible(value)
        self.progress.setValue(0)
        self.update_controls()

    def edit_avatar(self, edit):
        dialog = AvatarDialog(self, self.current_avatar if edit else None, self.pending_avatar if not edit else None)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.pending_avatar = dialog.payload()
            self.set_busy(True)
            self.status_text.setText(tr('Сохраняем голосовой аватар…'))
            self.backend.send(self.pending_avatar)

    def open_books(self):
        from book_ui import BookDialog
        if self.book_dialog:
            self.book_dialog.deleteLater()
        self.book_dialog = BookDialog(self)
        self.book_dialog.exec()

    def refresh_analysis_provider(self):
        import analysis_settings
        self.analysis_provider_label.setText(tr('Озвучка: на компьютере\nРазметка: ')+analysis_settings.label())

    def configure_analysis(self):
        if self.busy:return
        from analysis_settings_ui import AnalysisSettingsDialog
        if AnalysisSettingsDialog(self).exec():
            self.refresh_analysis_provider()
            if self.book_dialog:self.book_dialog.refresh_provider()

    def archive_avatar(self):
        if not self.current_avatar:
            return
        answer = QMessageBox.question(self, tr('Убрать аватар?'), tr('Аватар будет скрыт из библиотеки. Готовые записи сохранятся.'))
        if answer == QMessageBox.StandardButton.Yes:
            store.archive_profile(self.current_avatar['id'])
            self.refresh_avatars()

    def generate(self):
        if not self.current_avatar or self.busy:
            return
        self.player.stop()
        self.set_busy(True)
        self.status_text.setText(tr('Создаём озвучку выбранным голосом…'))
        self.backend.send(dict(action='generate', avatar_id=self.current_avatar['id'],
                               text=self.editor.toPlainText().strip(), seed=self.seed.value()))

    def refresh_history(self, selected=None):
        self.history_list.clear()
        entries = store.history()[:100]
        for record in entries:
            summary = record['text'].replace('\n', ' ')
            if len(summary) > 78:
                summary = summary[:75] + '…'
            item = QListWidgetItem(f'{record["avatar_name"]}   ·   {duration_text(record["duration"])}   ·   {record["created"].replace("T", "  ")}\n{summary}')
            item.setData(Qt.ItemDataRole.UserRole, record)
            item.setSizeHint(QSize(500, 63))
            self.history_list.addItem(item)
        if entries:
            index = next((i for i,x in enumerate(entries) if x['id'] == selected), 0)
            self.history_list.setCurrentRow(index)
        else:
            placeholder = QListWidgetItem(tr('Пока здесь тихо. Создайте первую озвучку — она сохранится здесь.'))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            self.history_list.addItem(placeholder)

    def select_record(self, current, previous=None):
        record = current.data(Qt.ItemDataRole.UserRole) if current else None
        if not record:
            return
        self.current_record = record
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(record['mp3']))
        self.track_name.setText(record['avatar_name'] + ' · ' + record['text'][:42] + ('…' if len(record['text'])>42 else ''))
        self.update_controls()

    def preview_reference(self):
        if self.current_avatar:
            self.current_record = None
            self.player.stop()
            self.player.setSource(QUrl.fromLocalFile(str(store.avatar_path(self.current_avatar))))
            self.track_name.setText(tr('Образец · ') + self.current_avatar['name'])
            self.player.play()
            self.update_controls()

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def update_playback(self, *args):
        self.seek.setMaximum(self.player.duration())
        if not self.seek.isSliderDown():
            self.seek.setValue(self.player.position())
        self.time.setText(duration_text(self.player.position()/1000) + ' / ' + duration_text(self.player.duration()/1000))

    def export(self, kind):
        if not self.current_record:
            return
        target, _ = QFileDialog.getSaveFileName(self, tr('Сохранить озвучку'), str(Path.home() / (tr('Озвучка.') + f'{kind}')), (tr('Аудио (*.') + f'{kind}' + ')'))
        if target:
            if not target.lower().endswith('.'+kind):
                target += '.'+kind
            try:
                source = Path(self.current_record[kind])
                if source.resolve() != Path(target).resolve():
                    shutil.copyfile(source, target)
                self.status_text.setText(tr('Запись сохранена: ') + target)
            except OSError as exc:
                QMessageBox.warning(self, tr('Не удалось сохранить'), str(exc))

    def closeEvent(self, event):
        if self.book_dialog and self.book_dialog.running and not getattr(self,'force_close',False):
            event.ignore()
            self.book_dialog.request_stop(close_app=True,confirm=False)
            return
        self.closing = True
        self.player.stop()
        try:
            store.atomic_json(store.DATA / 'settings.json', dict(
                avatar_id=self.current_avatar['id'] if self.current_avatar else None,
                draft=self.editor.toPlainText(), seed=self.seed.value()))
        finally:
            if self.backend:
                self.backend.stop()
        event.accept()


def main():
    if os.name == 'nt':
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('VoxStudio.Desktop.1')
    app = QApplication(sys.argv)
    app.setApplicationName('Vox Studio')
    app.setOrganizationName('Vox Studio Local')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setFont(QFont('Segoe UI', 10))
    store.DATA.mkdir(parents=True, exist_ok=True)
    key = 'vox-studio-' + hashlib.sha256(str(store.DATA.resolve()).encode()).hexdigest()[:16]
    lock = QLockFile(str(store.DATA / 'desktop.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        socket = QLocalSocket()
        socket.connectToServer(key)
        if socket.waitForConnected(1500):
            socket.write(b'show')
            socket.waitForBytesWritten(1000)
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    QLocalServer.removeServer(key)
    server.listen(key)
    store.bootstrap_previous_voices()
    import book_state
    book_state.recover()
    window = MainWindow()
    def activate():
        connection = server.nextPendingConnection()
        if connection:
            connection.deleteLater()
        window.showNormal()
        window.raise_()
        window.activateWindow()
    server.newConnection.connect(activate)
    app.aboutToQuit.connect(lambda: window.backend.stop() if window.backend else None)
    window.show()
    code = app.exec()
    server.close()
    lock.unlock()
    return code


if __name__ == '__main__':
    # pythonw has no console; retain unexpected GUI errors in a local log.
    (ROOT / 'logs').mkdir(exist_ok=True)
    if sys.stdout is None:
        sys.stdout = (ROOT / 'logs/desktop.log').open('a', encoding='utf-8', buffering=1)
    if sys.stderr is None:
        sys.stderr = sys.stdout
    sys.exit(main())
