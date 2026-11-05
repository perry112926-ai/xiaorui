import json
from pathlib import Path
import tempfile
import unittest
from app.companion_memory import CompanionMemory
from experiments.longmemeval_eval import prepare, summary, judge_prompt
from experiments.agent_public_eval import select

class ProtocolTests(unittest.TestCase):
    def test_ingestion_excludes_gold_labels_and_preserves_roles_and_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            memory=CompanionMemory(Path(directory)/'memory.db')
            item={'question_id':'q','answer':'SECRET_GOLD','answer_session_ids':['s1'],
                  'haystack_session_ids':['s2','s1'],'haystack_dates':['2025/02/01','2025/01/01'],
                  'haystack_sessions':[[{'role':'assistant','content':'later recommendation','has_answer':False}],
                                       [{'role':'user','content':'earlier preference','has_answer':True}]]}
            ids=prepare(memory,item)
            with memory.db() as db:rows=db.execute('SELECT text FROM episodes ORDER BY id').fetchall()
            text=json.dumps(rows)
            self.assertNotIn('has_answer',text);self.assertNotIn('SECRET_GOLD',text)
            self.assertIn('user: earlier preference',rows[0][0]);self.assertIn('assistant: later recommendation',rows[1][0])
            self.assertEqual(ids,{1:'s1',2:'s2'})

    def test_sampling_depends_on_ids_not_reference_answers(self):
        a=[{'sample_id':'user','qa':[{'category':c,'answer':'x'} for c in (1,1,2,2,3,3,4,4,5)]}]
        b=[{'sample_id':'user','qa':[{'category':c,'answer':'another'} for c in (1,1,2,2,3,3,4,4,5)]}]
        chosen=lambda data:[(r[1],r[2]) for r in select(data,1)]
        self.assertEqual(chosen(a),chosen(b));self.assertEqual(len(chosen(a)),4)

    def test_unscored_retrieval_rows_are_not_counted_as_qa_passes(self):
        rows=[{'id':'a','has_evidence':True,'all_evidence':True,'any_evidence':True},
              {'id':'b','has_evidence':True,'all_evidence':False,'any_evidence':False,'judge_pass':False},
              {'id':'c','has_evidence':True,'all_evidence':True,'any_evidence':True,'judge_pass':True}]
        result=summary(rows)
        self.assertEqual(result['n'],3);self.assertEqual(result['qa_n'],2);self.assertEqual(result['judge_accuracy'],.5)
