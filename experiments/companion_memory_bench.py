"""Public LoCoMo evidence retrieval evaluation, NOT answer accuracy.

Download upstream data/locomo10.json separately. All annotated evidence is held
out of indexing/ranking. Report all-evidence recall@k by category and hash input.
"""
import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from collections import defaultdict
from app.companion_memory import CompanionMemory


def run(path, k=8):
    raw=path.read_bytes(); data=json.loads(raw); results=[]
    with tempfile.TemporaryDirectory() as directory:
        memory=CompanionMemory(Path(directory)/'memory.db')
        for sample in data:
            owner=sample['sample_id']; ids={}
            for key, turns in sample['conversation'].items():
                if not isinstance(turns,list): continue
                date=sample['conversation'].get(key+'_date_time','')
                for turn in turns:
                    rid=memory.record(owner,0,f"{date} {turn['speaker']}: {turn['text']}")
                    ids[rid]=turn['dia_id']
            for qa in sample['qa']:
                evidence=set(qa.get('evidence',[]))
                if not evidence: continue
                recalled=memory.recall(owner,0,qa['question'],k)['episodes']
                found={ids[r['id']] for r in recalled}
                results.append({'category':qa['category'],'all_evidence':evidence<=found,'any_evidence':bool(evidence&found)})
    groups=defaultdict(list)
    for r in results: groups[str(r['category'])].append(r)
    def metrics(rows):
        return {'n':len(rows),'all_evidence_recall':sum(r['all_evidence'] for r in rows)/max(1,len(rows)), 'any_evidence_recall':sum(r['any_evidence'] for r in rows)/max(1,len(rows))}
    return {'dataset':'LoCoMo10','sha256':hashlib.sha256(raw).hexdigest(),'metric':f'evidence recall@{k}, not QA accuracy','overall':metrics(results),'categories':{key:metrics(rows) for key,rows in groups.items()}}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('dataset',type=Path);parser.add_argument('--k',type=int,default=8);parser.add_argument('--output',type=Path)
    args=parser.parse_args();result=run(args.dataset,args.k);encoded=json.dumps(result,indent=2);print(encoded)
    if args.output:args.output.write_text(encoded+'\n')
