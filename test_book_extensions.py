import gc,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import book_engine as books
import book_state as state
import book_cast as cast
import book_append
import avatar_store as store
import roles_analysis as roles

class ExtensionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.patches=[patch.object(books,'BOOKS',self.root/'books'),patch.object(store,'DATA',self.root)]
        for p in self.patches:p.start()
        source=self.root/'old.txt';source.write_text('Глава 1\n\nКейл посмотрел на Рона.\n\n— Привет.',encoding='utf-8')
        books.import_book(source,'book',lambda *a:None);state.migrate('book')
        with books.connect('book') as db:
            roles.ensure_schema(db)
            db.execute("INSERT INTO characters(name,avatar,category) VALUES('Кейл','hero','main')")
            db.execute("INSERT INTO character_aliases VALUES('кейл','Кейл')")
            db.execute("UPDATE segments SET analyzed=1,wav='saved.wav',signature='saved-signature'")
            db.execute("INSERT INTO chapter_context VALUES(1,'Кейл встретил Рона.')")
            db.execute('UPDATE characters SET portrait=?,user_notes=? WHERE name=?',(json.dumps(dict(role='Главный герой',state='Насторожен')),'Говорит спокойно','Кейл'))
        db.close();state.update('book',roles_model='older-model',analysis_complete=True,analyzed=True)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        gc.collect();self.tmp.cleanup()
    def test_voice_priority_counts_and_manual_category(self):
        with books.connect('book') as db:
            db.execute("UPDATE cast_categories SET avatar='group' WHERE id='main'")
            self.assertEqual(cast.voices(db)['Кейл'],'hero')
            db.execute("UPDATE characters SET avatar='',category_manual=1 WHERE name='Кейл'")
            self.assertEqual(cast.voices(db)['Кейл'],'group')
            cast.apply_category(db,dict(category='episodic'),'Кейл')
            self.assertEqual(db.execute("SELECT category FROM characters WHERE name='Кейл'").fetchone()[0],'main')
            parts=[dict(text='Привет',speaker='Кейл'),dict(text='Ещё',speaker='Кейл'),dict(text='сказал он',speaker=''),dict(text='Продолжим',speaker='Кейл')]
            db.execute('UPDATE segments SET parts=? WHERE id=2',(json.dumps(parts),))
            self.assertEqual(cast.counts(db)['Кейл'],2)
            self.assertEqual(books.voice_for({'speaker':'Кейл'},{'avatar':'chapter','mode':'roles'},cast.voices(db),{'default_avatar':'author'}),'group')
        db.close();state.snapshot('book')
        self.assertIn('categories',json.loads((books.folder('book')/'markup.json').read_text(encoding='utf-8')))
    def test_restart_audio_only_clears_selected_scope(self):
        with books.connect('book') as db:
            db.execute("INSERT INTO chapters(id,title,output) VALUES(2,'Вторая','second.mp3')")
            db.execute("INSERT INTO segments(id,chapter,text,analyzed,wav,signature) VALUES(99,2,'Вторая глава',1,'second.wav','second-signature')")
            before=[dict(r) for r in db.execute('SELECT id,text,speaker,parts,analyzed FROM segments ORDER BY id')]
        db.close()
        audio=books.folder('book')/'audio';audio.mkdir(exist_ok=True)
        for i in (1,2):(audio/f'chapter-{i:04d}-heading.heading.json').write_text('{}')
        state.restart_audio('book',1)
        with books.connect('book') as db:
            self.assertEqual(before,[dict(r) for r in db.execute('SELECT id,text,speaker,parts,analyzed FROM segments ORDER BY id')])
            self.assertEqual(db.execute('SELECT signature FROM segments WHERE id=99').fetchone()[0],'second-signature')
            self.assertEqual(db.execute("SELECT count(*) FROM segments WHERE chapter=1 AND signature!=''").fetchone()[0],0)
        db.close()
        self.assertFalse((audio/'chapter-0001-heading.heading.json').exists())
        self.assertTrue((audio/'chapter-0002-heading.heading.json').exists())
        state.restart_audio('book')
        with books.connect('book') as db:self.assertEqual(db.execute("SELECT count(*) FROM segments WHERE signature!=''").fetchone()[0],0)
        db.close()
        self.assertFalse((audio/'chapter-0002-heading.heading.json').exists())
        self.assertTrue(books.metadata('book')['analysis_complete'])
    def test_append_and_analyze_preserves_old_rows_and_context(self):
        with books.connect('book') as db:old=[dict(r) for r in db.execute('SELECT * FROM segments')]
        db.close()
        source=self.root/'next.txt';source.write_text('Глава 2\n\nРон принёс воду.',encoding='utf-8')
        result=book_append.append('book',source)
        self.assertEqual(result['first_chapter'],2)
        calls=[]
        class Fake:
            compact_roles=False;semantic_chapters=True
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def tokens(self,text):return len(text)//3
            def complete(self,text,schema,budget,callback):
                payload=json.loads(text.split('<|im_start|>user\n')[1].split('<|im_end|>')[0]);calls.append(payload)
                return dict(characters=[dict(name='Рон',aliases=[],category='supporting',category_reason='Помогает герою')],assignments=[dict(id=r['id'],speaker='',uncertain=False,parts=[dict(text=r['text'],speaker='',kind='content')],number_readings=['вторая'] if '2' in r['text'] else []) for r in payload['target_fragments']],summary='Рон принёс воду Кейлу.')
        roles.analyze('book',lambda *a:None,Fake)
        self.assertEqual(len(calls),1)
        self.assertIn('Кейл встретил Рона',calls[0]['previous_summary'])
        self.assertIn('Кейл',calls[0]['previous_text'])
        self.assertEqual(calls[0]['known_characters'][0]['name'],'Кейл')
        self.assertIn('dialogue_count',calls[0]['known_characters'][0])
        self.assertEqual(calls[0]['known_characters'][0]['portrait']['role'],'Главный герой')
        self.assertEqual(calls[0]['known_characters'][0]['user_notes'],'Говорит спокойно')
        self.assertTrue(all(r['id']>old[-1]['id'] for r in calls[0]['target_fragments']))
        with books.connect('book') as db:
            current=[dict(r) for r in db.execute('SELECT * FROM segments WHERE chapter=1')]
            self.assertEqual(current,old)
            self.assertEqual(cast.voices(db)['Кейл'],'hero')
            self.assertIsNone(book_append.boundary(db))
        db.close()
        self.assertTrue(books.metadata('book')['analysis_complete'])
    def test_failed_append_rolls_back(self):
        def broken(*args):
            yield 'Глава новая',True
            raise ValueError('Unreadable')
        with patch.object(books,'blocks',broken),self.assertRaises(ValueError):book_append.append('book','unused')
        with books.connect('book') as db:self.assertEqual(db.execute('SELECT count(*) FROM chapters').fetchone()[0],1)
        db.close()

    def test_ui_groups_and_append_controls(self):
        import os
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        from PySide6.QtWidgets import QApplication,QWidget
        from book_ui import BookDialog
        app=QApplication.instance() or QApplication([])
        host=QWidget();host.ready=False
        dialog=BookDialog(host)
        try:
            self.assertTrue(dialog.append_button.isEnabled())
            self.assertEqual(dialog.cast.columnCount(),3)
            self.assertEqual(dialog.cast.rowCount(),4)
            dialog.set_category('Кейл','episodic');app.processEvents()
            with books.connect('book') as db:self.assertEqual(db.execute('SELECT category FROM characters').fetchone()[0],'episodic')
            db.close()
            dialog.set_running(True);self.assertFalse(dialog.append_button.isEnabled())
            dialog.set_running(False)
            Path('outputs').mkdir(exist_ok=True)
            dialog.resize(1180,800);dialog.show();app.processEvents();dialog.grab().save('outputs/book-categories-preview.png')
        finally:
            dialog.shelf_timer.stop();dialog.allow_close=True;dialog.close();dialog.deleteLater();host.deleteLater();app.processEvents()

    def test_append_resume_does_not_repeat_completed_api_batch(self):
        source=self.root/'long.txt';source.write_text('Глава новая\n\n'+'\n\n'.join('Рон принёс воду.' for _ in range(25)),encoding='utf-8')
        book_append.append('book',source)
        calls=[];fail=[True]
        class Fake:
            compact_roles=False;semantic_chapters=False
            def __init__(self,*args):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def tokens(self,text):return len(text)//3
            def complete(self,text,schema,budget,callback):
                payload=json.loads(text.split('<|im_start|>user\n')[1].split('<|im_end|>')[0]);rows=payload['target_fragments'];calls.append([r['id'] for r in rows])
                if len(calls)==2 and fail[0]:raise RuntimeError('Connection interrupted')
                return dict(characters=[],assignments=[dict(id=r['id'],speaker='',uncertain=False,parts=[dict(text=r['text'],speaker='',kind='content')],number_readings=[]) for r in rows],summary='Рон принёс воду.')
        with self.assertRaises(RuntimeError):roles.analyze('book',lambda *a:None,Fake)
        fail[0]=False;roles.analyze('book',lambda *a:None,Fake)
        self.assertEqual(len(calls),3)
        self.assertEqual(calls[1],calls[2])
        self.assertNotEqual(calls[0],calls[2])

if __name__=='__main__':unittest.main()
