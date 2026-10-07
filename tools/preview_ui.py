import os,tempfile,json
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen';os.environ['VOX_UI_LANGUAGE']='en'
tmp=tempfile.TemporaryDirectory();os.environ['VOX_DATA_DIR']=tmp.name
from PySide6.QtWidgets import QApplication
from desktop_app import MainWindow,STYLE
from analysis_settings_ui import AnalysisSettingsDialog
import avatar_store as store
app=QApplication([])
from PySide6.QtGui import QFontDatabase,QFont
for filename in ('segoeui.ttf','seguisb.ttf','segoeuib.ttf','seguisym.ttf'):
 QFontDatabase.addApplicationFont(str(Path(os.environ['WINDIR'])/'Fonts'/filename))
app.setFont(QFont('Segoe UI',10));app.setStyleSheet(STYLE)
for ident,name in [('narrator','Narrator'),('hero','Alex'),('guest','Morgan')]:
 store.atomic_json(store.DATA/'avatars'/ident/'avatar.json',dict(id=ident,name=name,created='2026-01-01',duration=12,transcript='A sample voice for the interface preview.'))
from avatar_folders import create
from avatar_folders import move
fid=create('Story voices');move(['narrator','hero','guest'],fid)
window=MainWindow(start_backend=False);window.resize(1280,900);window.stack.setCurrentIndex(1);window.ready=True;window.update_controls();window.editor.setPlainText('The train slowed as the mountains came into view.\n\n“Do you think we will find it?” Alex asked.\n\nMorgan smiled. “There is only one way to find out.”')
window.show();app.processEvents()
Path('docs/screenshots').mkdir(parents=True,exist_ok=True)
window.grab().save('docs/screenshots/studio.png')
dialog=AnalysisSettingsDialog(window);dialog.provider.setCurrentIndex(dialog.provider.findData('openrouter'));dialog.model.setCurrentText('Choose a model or enter its ID');dialog.show();app.processEvents();dialog.grab().save('docs/screenshots/api-settings.png');dialog.close()
import book_engine as books,book_state as state,roles_analysis as roles
source=Path(tmp.name)/'The mountain railway.txt';source.write_text('Chapter 1 — A new journey\n\nThe train slowed as the mountains came into view.\n\n“Do you think we will find it?” Alex asked.\n\nMorgan smiled. “There is only one way to find out.”',encoding='utf-8')
books.import_book(source,'preview',lambda *a:None);state.migrate('preview')
with books.connect('preview') as db:
 roles.ensure_schema(db)
 db.execute("UPDATE chapters SET title='Chapter 1 — A new journey'")
 db.execute("INSERT INTO characters(name,avatar,category,mentions) VALUES('Alex','hero','main',1)")
 db.execute("INSERT INTO characters(name,avatar,category,mentions) VALUES('Morgan','guest','supporting',1)")
 db.execute("UPDATE segments SET analyzed=1")
 db.execute("UPDATE segments SET speaker='Alex' WHERE id=3")
 db.execute("UPDATE segments SET speaker='Morgan' WHERE id=4")
db.close()
state.update('preview',stage='analysis',job_status='done',default_avatar='narrator',analysis_complete=True,analysis_percent=100,analyzed=True,roles_model='preview-v16-portraits')
from book_ui import BookDialog
book=BookDialog(window);book.resize(1450,980);book.show();app.processEvents();book.grab().save('docs/screenshots/audiobooks.png');book.hide()
print('English studio, books and API screenshots saved')
window.hide()


import gc
gc.collect()
tmp.cleanup()
