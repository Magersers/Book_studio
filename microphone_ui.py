"""Explicit-start microphone recording, meter, review and WAV capture."""
from ui_language import tr
import time
import uuid
from pathlib import Path
from PySide6.QtCore import QTimer,QUrl
from PySide6.QtWidgets import QDialog,QVBoxLayout,QHBoxLayout,QLabel,QPushButton,QComboBox,QProgressBar,QMessageBox
from PySide6.QtMultimedia import QMediaDevices,QAudioSource,QAudioFormat,QAudio,QMediaPlayer,QAudioOutput
import avatar_store as store

def pcm_float(raw,format):
    import numpy as np
    types={QAudioFormat.SampleFormat.UInt8:'uint8',QAudioFormat.SampleFormat.Int16:'int16',QAudioFormat.SampleFormat.Int32:'int32',QAudioFormat.SampleFormat.Float:'float32'}
    width=format.bytesPerFrame()
    raw=raw[:len(raw)//width*width]
    data=np.frombuffer(raw,dtype=types[format.sampleFormat()]).astype('float32')
    if format.sampleFormat()==QAudioFormat.SampleFormat.UInt8: data=(data-128)/128
    elif format.sampleFormat()==QAudioFormat.SampleFormat.Int16: data/=32768
    elif format.sampleFormat()==QAudioFormat.SampleFormat.Int32: data/=2147483648
    return data.reshape(-1,format.channelCount()).mean(axis=1)

class RecordDialog(QDialog):
    def __init__(self,parent):
        super().__init__(parent); self.setWindowTitle(tr('Запись голоса')); self.setMinimumWidth(520)
        self.source=None; self.stream=None; self.raw=bytearray(); self.path=''; self.duration=0
        layout=QVBoxLayout(self); layout.setSpacing(16)
        title=QLabel(tr('Ваш голос — новый аватар')); title.setObjectName('subtitle'); layout.addWidget(title)
        hint=QLabel(tr('Прочитайте 6–15 секунд спокойным голосом.\nЗапись начнётся только после нажатия кнопки; максимум 30 секунд.')); hint.setWordWrap(True); layout.addWidget(hint)
        self.devices=QMediaDevices.audioInputs(); self.device=QComboBox()
        for dev in self.devices: self.device.addItem(dev.description())
        default=QMediaDevices.defaultAudioInput()
        self.device.setCurrentIndex(next((i for i,d in enumerate(self.devices) if d.id()==default.id()),0))
        layout.addWidget(self.device)
        self.status=QLabel(tr('Готов к записи') if self.devices else tr('Микрофон не найден. Подключите устройство и откройте это окно снова.'))
        self.status.setWordWrap(True); layout.addWidget(self.status)
        self.meter=QProgressBar(); self.meter.setRange(0,100); layout.addWidget(self.meter)
        row=QHBoxLayout(); self.record=QPushButton(tr('● Начать запись')); self.record.setObjectName('primary'); self.record.clicked.connect(self.toggle); self.record.setEnabled(bool(self.devices)); row.addWidget(self.record)
        self.listen=QPushButton(tr('Прослушать')); self.listen.clicked.connect(self.preview); self.listen.setEnabled(False); row.addWidget(self.listen); layout.addLayout(row)
        self.use=QPushButton(tr('Использовать запись')); self.use.setEnabled(False); self.use.clicked.connect(self.accept); layout.addWidget(self.use)
        self.player=QMediaPlayer(self); self.output=QAudioOutput(self); self.player.setAudioOutput(self.output)
        self.timer=QTimer(self); self.timer.setInterval(80); self.timer.timeout.connect(self.tick)
    def toggle(self):
        if self.source: self.stop(); return
        self.player.stop(); self.raw=bytearray(); self.path=''; self.use.setEnabled(False); self.listen.setEnabled(False)
        device=self.devices[self.device.currentIndex()]; self.format=device.preferredFormat()
        self.source=QAudioSource(device,self.format,self); self.source.setBufferSize(self.format.bytesForDuration(100000))
        self.stream=self.source.start()
        if self.stream is None or self.source.error()!=QAudio.Error.NoError:
            self.source.stop(); self.source.deleteLater(); self.source=None
            self.status.setText(tr('Нет доступа к микрофону. Проверьте устройство и разрешение микрофона для настольных приложений в Windows.')); return
        self.started=time.monotonic(); self.device.setEnabled(False); self.record.setText(tr('■ Остановить')); self.timer.start()
    def drain(self):
        if self.stream:
            raw=bytes(self.stream.readAll()); self.raw.extend(raw)
            if raw:
                import numpy as np
                values=pcm_float(raw,self.format)
                if len(values): self.meter.setValue(min(100,int(float(np.max(np.abs(values)))*100)))
    def tick(self):
        self.drain(); elapsed=time.monotonic()-self.started
        self.status.setText((tr('Запись · ') + f'{elapsed:.1f}' + tr(' / 30 секунд')))
        if self.source.error()!=QAudio.Error.NoError:
            self.stop(); self.status.setText(tr('Устройство отключилось или запись прервалась. Проверьте полученный образец.')); return
        if elapsed>=30: self.stop()
    def stop(self):
        if not self.source: return
        self.timer.stop(); self.drain(); self.source.stop(); self.source.deleteLater(); self.source=None; self.stream=None
        self.record.setText(tr('● Записать заново')); self.device.setEnabled(True)
        import numpy as np
        import soundfile as sf
        values=pcm_float(self.raw,self.format)[:self.format.sampleRate()*30]
        self.duration=len(values)/self.format.sampleRate()
        if self.duration<3 or (len(values) and float(np.max(np.abs(values)))<.005):
            self.status.setText(tr('Образец слишком короткий или тихий. Запишите минимум 3 секунды слышимой речи.')); return
        dest=store.DATA/'recordings'; dest.mkdir(parents=True,exist_ok=True)
        path=dest/(uuid.uuid4().hex+'.wav'); sf.write(path,values,self.format.sampleRate(),subtype='PCM_16'); self.path=str(path)
        self.status.setText((tr('Записано ') + f'{self.duration:.1f}' + tr(' секунд. Прослушайте образец перед сохранением.'))); self.listen.setEnabled(True); self.use.setEnabled(True)
    def preview(self):
        self.player.setSource(QUrl.fromLocalFile(self.path)); self.player.play()
    def done(self,result):
        self.stop(); self.player.stop(); super().done(result)
