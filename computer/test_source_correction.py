import hashlib,json,sqlite3,unittest
from source_correction import correct_sources


class SourceCorrectionTests(unittest.TestCase):
    def test_exact_retraction_preserves_unrelated_facts_and_ids_and_is_idempotent(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        self.addCleanup(db.close)
        db.executescript('CREATE TABLE archive(op_id TEXT PRIMARY KEY,role TEXT,content TEXT);CREATE TABLE operations(op_id TEXT,result INTEGER);CREATE TABLE device(singleton INTEGER PRIMARY KEY,memory TEXT,identity TEXT,revision INTEGER);')
        memory={'next_id':9,'history':[{'id':1,'role':'user','content':'我的爱好是喝茶'},{'id':2,'role':'user','content':'误收的背景话'}],'pending':[{'id':2,'content':'误收的背景话'}],'cards':[{'source_id':1,'text':'喜欢喝茶'},{'source_id':2,'text':'错误事实'}],'growth':[{'evidence':[2]}],'changes':[],'summary':'过期摘要'}
        db.execute('INSERT INTO device VALUES(1,?,?,5)',(json.dumps(memory),'identity-unchanged'))
        db.execute('INSERT INTO archive VALUES(?,?,?)',('a','user','误收的背景话'));db.execute('INSERT INTO operations VALUES(?,?)',('a',2));db.commit()
        target={'seq':1,'role':'user','sha256':hashlib.sha256('误收的背景话'.encode()).hexdigest(),'reason':'owner_confirmed_not_addressed'}
        with self.assertRaises(ValueError):
            with db:correct_sources(db,[target|{'sha256':'wrong'}])
        self.assertEqual(db.execute('SELECT count(*) FROM archive').fetchone()[0],1)
        with db:result=correct_sources(db,[target])
        self.assertEqual(result['retracted'],1)
        row=db.execute('SELECT * FROM device').fetchone();new=json.loads(row['memory'])
        self.assertEqual(row['identity'],'identity-unchanged');self.assertEqual(new['next_id'],9)
        self.assertEqual(new['cards'],[{'source_id':1,'text':'喜欢喝茶'}]);self.assertEqual(len(new['history']),1)
        self.assertFalse(new['growth']);self.assertFalse(new['summary'])
        with db:self.assertEqual(correct_sources(db,[target])['retracted'],0)
