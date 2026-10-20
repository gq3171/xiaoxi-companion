import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import release_runtime as release

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.install=self.root/'installed';self.bundle=self.root/'bundle';self.base=self.root/'data'
        self.install.mkdir();self.bundle.mkdir();(self.base/'state').mkdir(parents=True)
        for name in ('jobs','web-chat'):
            db=sqlite3.connect(self.base/'state'/(name+'.sqlite3'));db.execute('CREATE TABLE '+('jobs' if name=='jobs' else 'turns')+'(state TEXT)');db.commit();db.close()
        files={};baseline={}
        for name in ('agent.py','brain.py','companion.py','new_module.py'):
            if name!='new_module.py':(self.install/name).write_text('old '+name)
            (self.bundle/name).write_text('new '+name);files[name]=release.sha(self.bundle/name);baseline[name]=release.sha(self.install/name) if (self.install/name).exists() else None
        (self.bundle/'tests.log').write_text('isolated fixture proof')
        self.manifest={'format':1,'runtime_contract':'desktop-v1','files':files,'baseline':baseline,'checks':{name:{'status':'passed','evidence':'tests.log','sha256':release.sha(self.bundle/'tests.log')} for name in release.GATES}}
        self.save()
    def save(self):(self.bundle/'manifest.json').write_text(json.dumps(self.manifest))
    def tearDown(self):self.tmp.cleanup()
    def test_changed_source_baseline_evidence_and_unsafe_path_are_rejected(self):
        for mutation in ('entrypoint','evidence','escape','baseline'):
            with self.subTest(mutation=mutation):
                old=json.loads(json.dumps(self.manifest))
                if mutation=='entrypoint':self.manifest['runtime_contract']='draft-v2'
                elif mutation=='evidence':self.manifest['checks']['arm_unit']['sha256']='wrong'
                elif mutation=='escape':self.manifest['files']['../other.py']='wrong'
                else:self.manifest['baseline']['brain.py']='wrong'
                self.save()
                with self.assertRaises((ValueError,OSError)):release.validate(self.bundle,self.install)
                self.manifest=old;self.save()
    def test_successful_activation_and_health_failure_roll_back_sources_not_live_database(self):
        for fail in (False,True):
            with self.subTest(fail=fail):
                original={p.name:p.read_bytes() for p in self.install.iterdir()}
                actions=[]
                def health(base):
                    if fail:
                        with sqlite3.connect(base/'state/jobs.sqlite3') as db:db.execute("INSERT INTO jobs VALUES('preserve-new-record')")
                        raise RuntimeError('synthetic unavailable')
                    return {'ready':True}
                # The deterministic clock expires after one health failure.
                with patch.object(release.time,'monotonic',side_effect=[0,31]):
                    if fail:
                        with self.assertRaises(RuntimeError):release.activate(self.bundle,self.install,self.base,actions.append,health)
                        self.assertEqual({p.name:p.read_bytes() for p in self.install.iterdir()},original)
                        with sqlite3.connect(self.base/'state/jobs.sqlite3') as db:self.assertEqual(db.execute('SELECT state FROM jobs').fetchone()[0],'preserve-new-record')
                        self.assertEqual(actions,['stop','start','stop','start'])
                    else:
                        release.activate(self.bundle,self.install,self.base,actions.append,health)
                        self.assertEqual(actions,['stop','start'])
                if not fail:
                    # Reset a new isolated fixture; not a production database rollback.
                    self.tearDown();self.setUp()
