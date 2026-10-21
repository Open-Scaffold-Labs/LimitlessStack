"""Main-agent lifecycle audit: real candidate functions, network-free adversarial backend."""
import ast
from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
ROOT=Path(__file__).parent
sys.path.insert(0,str(ROOT))
import notebooklm_sync_safety as safety
spec=importlib.util.spec_from_file_location('audited_refresh',ROOT/'notebooklm-wiki-refresh.py')
rf=importlib.util.module_from_spec(spec);sys.modules[spec.name]=rf;spec.loader.exec_module(rf)

verify_actual=rf.cmd_verify_content

class Backend:
 def __init__(self):
  self.live={'old':{'title':'log.md','status':'ready'}};self.adds=0;self.deletes=[];self.verify=True;self.crash=False;self.fail_delete=False
 def run(self,args):
  return subprocess.CompletedProcess(args,0,json.dumps({'sources':[dict(id=k,**v) for k,v in self.live.items()]}),'')
 def add(self,path):
  self.adds+=1;sid=f'new-{self.adds}';self.live[sid]={'title':path.name,'status':'ready'}
  if self.crash: self.crash=False;raise KeyboardInterrupt('after server registration')
  return sid
 def delete(self,sid):
  self.deletes.append(sid)
  if self.fail_delete:return False
  self.live.pop(sid,None);return True

class Safety(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.tools=self.root/'tools';self.tools.mkdir();self.path=self.root/'wiki/log.md';self.path.parent.mkdir();self.path.write_text('An original input with sufficient useful content for verification.\n');self.backend=Backend()
  self.ps=[patch.object(rf,'VAULT',self.root),patch.object(rf,'STATE_DIR',self.tools),patch.object(rf,'TOOLS',self.tools),patch.object(rf,'_ACTIVE_NOTEBOOK','notebook-A'),patch.object(rf,'run_nb',self.backend.run),patch.object(rf,'cmd_add',self.backend.add),patch.object(rf,'cmd_verify_content',lambda *a,**k:self.backend.verify),patch.object(rf,'cmd_delete',self.backend.delete),patch.object(rf,'source_present',lambda sid:sid in self.backend.live)]
  for p in self.ps:p.start()
 def tearDown(self):
  for p in reversed(self.ps):p.stop()
  self.tmp.cleanup()
 def journals(self):return list((self.tools/'.notebooklm-pending').glob('*/operation.json'))
 def test_rejected_candidate_preserves_old_and_does_not_reupload(self):
  self.backend.verify=False
  for _ in range(2):
   with self.assertRaises(rf.SyncVerificationError):rf.cmd_replace(self.path,'old')
  self.assertIn('old',self.backend.live);self.assertEqual(self.backend.deletes,[]);self.assertEqual(self.backend.adds,1);self.assertEqual(json.loads(self.journals()[0].read_text())['source_id'],'new-1')
 def test_success_verifies_before_retirement(self):
  def verify(sid,path,**kw):self.assertIn('old',self.backend.live);self.assertEqual(path.read_bytes(),self.path.read_bytes());return True
  with patch.object(rf,'cmd_verify_content',verify):self.assertEqual(rf.cmd_replace(self.path,'old'),('new-1',True,True))
  self.assertEqual(self.backend.deletes,['old']);self.assertIn('new-1',self.backend.live)
 def test_registration_crash_resumes_exact_candidate(self):
  self.backend.crash=True
  with self.assertRaises(KeyboardInterrupt):rf.cmd_replace(self.path,'old')
  self.assertIn('old',self.backend.live)
  self.assertEqual(rf.cmd_replace(self.path,'old')[0],'new-1');self.assertEqual(self.backend.adds,1)
 def test_ambiguous_registration_stops(self):
  self.backend.crash=True
  with self.assertRaises(KeyboardInterrupt):rf.cmd_replace(self.path,'old')
  self.backend.live['extra']={'title':'log.md','status':'ready'}
  with self.assertRaisesRegex(rf.SyncVerificationError,'Uncertain registration'):rf.cmd_replace(self.path,'old')
  self.assertEqual(self.backend.deletes,[]);self.assertEqual(self.backend.adds,1)
 def test_changed_input_during_pending_stops(self):
  self.backend.verify=False
  with self.assertRaises(rf.SyncVerificationError):rf.cmd_replace(self.path,'old')
  self.path.write_text('Changed input')
  with self.assertRaisesRegex(rf.SyncVerificationError,'different input'):rf.cmd_replace(self.path,'old')
  self.assertIn('old',self.backend.live);self.assertEqual(self.backend.adds,1)
 def test_crash_after_verified_candidate_recovers_without_upload(self):
  self.backend.fail_delete=True
  with self.assertRaises(rf.SyncVerificationError):rf.cmd_replace(self.path,'old')
  self.backend.fail_delete=False
  self.assertEqual(rf.cmd_replace(self.path,'old')[0],'new-1');self.assertEqual(self.backend.adds,1)
 def test_journal_survives_until_verified_receipt(self):
  sid=rf.cmd_replace(self.path,'old')[0];safety.finish_receipts(self.tools);self.assertEqual(len(self.journals()),1)
  rf.save_state(self.tools/'.notebooklm-wiki-state.json',{'wiki/log.md':{'source_id':sid}});self.assertEqual(len(self.journals()),1)
  rf.save_state(self.tools/'.notebooklm-wiki-state.json',{'wiki/log.md':{'source_id':sid,'verified_at':1}});self.assertEqual(self.journals(),[])
 def test_atomic_state_interruption_preserves_previous_json(self):
  path=self.tools/'.notebooklm-wiki-state.json';rf.save_state(path,{'previous':1})
  with patch.object(safety.os,'replace',side_effect=OSError('crash before rename')):
   with self.assertRaises(OSError):rf.save_state(path,{'next':2})
  self.assertEqual(json.loads(path.read_text()),{'previous':1})
 def test_corrupt_receipt_is_not_silently_reset(self):
  path=self.tools/'broken.json';path.write_text('{')
  with self.assertRaises(rf.SyncVerificationError):rf.load_state(path)
 def test_readonly_count_can_run_while_writer_lock_is_held(self):
  import shutil
  for name in ['notebooklm-wiki-refresh.py','notebooklm_sync_safety.py','notebooklm_log_exports.py']:
   shutil.copy2(ROOT/name,self.tools/name)
  with safety.sync_lock(self.tools):
   p=subprocess.run([sys.executable,'-B',str(self.tools/'notebooklm-wiki-refresh.py'),'--count-routed','wiki'],capture_output=True,text=True)
  self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(p.stdout.strip(),'1')
 def test_concurrent_refresh_lock_rejects_second_writer(self):
  with safety.sync_lock(self.tools):
   with self.assertRaisesRegex(RuntimeError,'Another NotebookLM refresh'):
    with safety.sync_lock(self.tools):pass
 def test_failed_route_preserves_receipt_and_predecessor(self):
  state=self.tools/'.notebooklm-wiki-state.json';old={'wiki/log.md':{'mtime':0,'source_id':'old','verified_at':1}};rf.save_state(state,old);self.backend.verify=False
  with self.assertRaises(rf.SyncVerificationError):rf.sync_route('notebook-A','wiki','wiki',[self.path],False)
  self.assertEqual(json.loads(state.read_text()),old);self.assertIn('old',self.backend.live)
 def test_unverified_mtime_does_not_skip(self):
  state=self.tools/'.notebooklm-wiki-state.json';rf.save_state(state,{'wiki/log.md':{'mtime':self.path.stat().st_mtime,'source_id':'old'}})
  rf.sync_route('notebook-A','wiki','wiki',[self.path],False)
  self.assertEqual(self.backend.adds,1);self.assertTrue(json.loads(state.read_text())['wiki/log.md']['verified_at'])
 def test_missing_live_source_does_not_skip_verified_receipt(self):
  state=self.tools/'.notebooklm-wiki-state.json';rf.save_state(state,{'wiki/log.md':{'mtime':self.path.stat().st_mtime,'source_id':'gone','verified_at':1}})
  rf.sync_route('notebook-A','wiki','wiki',[self.path],False);self.assertEqual(self.backend.adds,1)
 def test_changed_sha_even_same_mtime_does_not_skip(self):
  state=self.tools/'.notebooklm-wiki-state.json';rf.save_state(state,{'wiki/log.md':{'mtime':self.path.stat().st_mtime,'source_id':'old','verified_at':1,'sha256':'wrong'}})
  rf.sync_route('notebook-A','wiki','wiki',[self.path],False);self.assertEqual(self.backend.adds,1)
 def test_second_split_failure_does_not_delete_legacy(self):
  first=self.root/'tools/notebooklm-exports/log-older-001.md';first.parent.mkdir();first.write_text('older');second=first.with_name('log-recent.md');second.write_text('newer');state=self.tools/'.notebooklm-wiki-state.json';rf.save_state(state,{'wiki/log.md':{'source_id':'old','mtime':0}})
  def verify(sid,path,**kw):return path.name!='log-recent.md'
  with patch.object(rf,'cmd_verify_content',verify):
   with self.assertRaises(rf.SyncVerificationError):rf.sync_route('notebook-A','wiki','wiki',[first,second],False)
  self.assertIn('old',self.backend.live);self.assertEqual(self.backend.deletes,[]);self.assertIn('wiki/log.md',json.loads(state.read_text()))
 def test_all_parts_verified_before_legacy_retirement(self):
  first=self.tools/'notebooklm-exports/log-older-001.md';first.parent.mkdir();first.write_text('older');second=first.with_name('log-recent.md');second.write_text('newer');state=self.tools/'.notebooklm-wiki-state.json';rf.save_state(state,{'wiki/log.md':{'source_id':'old','mtime':0}})
  def delete(sid):
   if sid=='old':self.assertEqual(self.backend.adds,2);self.assertEqual(len(json.loads(state.read_text())),3)
   return self.backend.delete(sid)
  with patch.object(rf,'cmd_delete',delete):rf.sync_route('notebook-A','wiki','wiki',[first,second],False)
  self.assertNotIn('wiki/log.md',json.loads(state.read_text()));self.assertNotIn('old',self.backend.live)
 def test_no_title_wide_deletion(self):
  self.backend.live['another-route']={'title':'log.md','status':'ready'};rf.cmd_replace(self.path,'old');self.assertIn('another-route',self.backend.live)
 def test_readiness_error_exposes_counter(self):
  with patch.object(rf,'run_nb',return_value=subprocess.CompletedProcess([],1,'{"status":"error"}','')),patch.object(rf,'_processing_error_detail',return_value='525143/500000'):
   with self.assertRaisesRegex(rf.SyncVerificationError,'525143/500000'):rf._require_ready('failed')
 def test_readiness_requires_exit_zero_and_ready(self):
  for code,status in [(0,'error'),(2,'ready'),(0,'unknown')]:
   with patch.object(rf,'run_nb',return_value=subprocess.CompletedProcess([],code,json.dumps({'status':status}),'')),patch.object(rf,'_processing_error_detail',return_value='detail'):
    with self.assertRaises(rf.SyncVerificationError):rf._require_ready('bad')
 def test_log_tail_must_be_present_in_indexed_text(self):
  path=self.path.with_name('log-recent.md');old='# Log\n\n## [2026-10-20] build | history\n'+('Repeated ordinary prose with stable sampled content. '*500);full=old+'\n## [2026-10-21] build | latest durable correction\nThis newest entry must be present in the indexed source, including its closing words.\n';path.write_text(full)
  content=[old]
  def run(args):
   if args[:2]==['source','wait']:return subprocess.CompletedProcess(args,0,'{"status":"ready"}','')
   Path(args[args.index('-o')+1]).write_text(content[0]);return subprocess.CompletedProcess(args,0,'','')
  with patch.object(rf,'run_nb',run):
   self.assertFalse(verify_actual('candidate',path,wait_retries=1))
   content[0]=full;self.assertTrue(verify_actual('candidate',path,wait_retries=1))
 def test_ready_positive_control(self):
  with patch.object(rf,'run_nb',return_value=subprocess.CompletedProcess([],0,'{"status":"ready"}','')):rf._require_ready('good')

if __name__=='__main__':unittest.main(verbosity=2)
