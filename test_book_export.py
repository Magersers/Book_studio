import tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from book_export import export

class ExportTest(unittest.TestCase):
    def test_single_chapter_ignores_unfinished_chapters_and_copies_bytes(self):
        import sqlite3
        from contextlib import contextmanager
        from book_export import chapters
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'ready.mp3';source.write_bytes(b'original mp3 bytes')
            db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
            db.executescript('CREATE TABLE chapters(id INTEGER,title TEXT,output TEXT); CREATE TABLE segments(id INTEGER,chapter INTEGER);')
            db.executemany('INSERT INTO chapters VALUES(?,?,?)',[(1,'Первая',str(source)),(2,'Вторая','')])
            db.executemany('INSERT INTO segments VALUES(?,?)',[(1,1),(2,2)])
            @contextmanager
            def connect(_):yield db
            with patch('book_export.books.connect',connect),patch('book_cast.voices',return_value={}),patch('book_export.books.metadata',return_value={}),patch('book_export.books.segment_plan',return_value=[{'text':'Речь'}]):
                result=export('book',root/'chapter.mp3','chapter',chapter_id=1)
                self.assertEqual(result.read_bytes(),source.read_bytes())
                with self.assertRaises(ValueError):chapters('book')
                with self.assertRaises(ValueError):export('book',root/'missing.mp3','chapter',chapter_id=2)
                with self.assertRaises(ValueError):export('book',source,'chapter',chapter_id=1)
                with self.assertRaises(ValueError):export('book',root/'none.mp3','chapter')
                self.assertEqual(source.read_bytes(),b'original mp3 bytes')
            db.close()

    def test_zip_preserves_files_and_orders_duplicate_titles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);a=root/'a.mp3';c=root/'c.mp3';a.write_bytes(b'first');c.write_bytes(b'second')
            with patch('book_export.chapters',return_value=[(1,'Глава / один',a),(3,'Глава / один',c)]):
                result=export('id',root/'result.zip','chapters')
                with zipfile.ZipFile(result) as z:
                    names=z.namelist();self.assertEqual(len(names),2)
                    self.assertTrue(names[0].startswith('001'));self.assertTrue(names[1].startswith('002'))
                    self.assertEqual([z.read(n) for n in names],[b'first',b'second'])
                with self.assertRaises(ValueError):export('id',a,'chapters')
                self.assertEqual(a.read_bytes(),b'first')
    def test_incomplete_book_leaves_existing_export_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'result.zip';target.write_bytes(b'previous')
            with patch('book_export.chapters',side_effect=ValueError('Incomplete')):
                with self.assertRaises(ValueError):export('id',target,'chapters')
            self.assertEqual(target.read_bytes(),b'previous')

if __name__=='__main__':unittest.main()
