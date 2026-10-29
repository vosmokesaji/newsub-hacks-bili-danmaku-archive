"""Append real user playback feedback for the explicitly identified ASS version."""
import argparse
from datetime import datetime,timezone
import json
import math
import re
from build_playback_checklist import ROOT,build_data,fingerprint,write_outputs

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode')
    scope=parser.add_mutually_exclusive_group(required=True)
    scope.add_argument('--checkpoint',help='check ID printed in the checklist, e.g. S03E02-J02')
    scope.add_argument('--whole-episode',action='store_true',help='general episode feedback, not individual checks')
    parser.add_argument('--ass-sha256',required=True,help='current full SHA256 or its first 12+ characters from the checklist')
    parser.add_argument('--result',required=True,choices=['pass','early','late','inconsistent','cannot_judge'])
    parser.add_argument('--amount-seconds',type=float,help='positive observed early/late amount; does not shift the timeline')
    parser.add_argument('--notes',required=True,help='actual user feedback, not an inferred or automatic pass')
    args=parser.parse_args()
    if not args.notes.strip():raise ValueError('Actual playback feedback is required')
    if args.amount_seconds is not None:
        if args.result not in['early','late']or not math.isfinite(args.amount_seconds)or args.amount_seconds<=0:
            raise ValueError('Only early/late observations accept a positive amount')
    data=build_data();episode=next((e for e in data['episodes']if e['episode']==args.episode),None)
    if not episode or not episode['playback_available']:raise ValueError('No current playback ASS for this episode')
    supplied=args.ass_sha256.lower()
    if not re.fullmatch(r'[0-9a-f]{12,64}',supplied)or not episode['ass_sha256'].startswith(supplied):
        raise ValueError('Feedback ASS version does not match the current checklist; do not apply old playback results to a new file')
    point=next((p for p in episode['checkpoints']if p['id']==args.checkpoint),None)if args.checkpoint else None
    if args.checkpoint and point is None:raise ValueError('Checkpoint not found for this episode')
    record={'episode':args.episode,'scope':'checkpoint'if point else'episode',
        'checkpoint_id':point['id']if point else None,'checkpoint_version':point['version']if point else None,
        'episode_version':episode['episode_version'],'ass_sha256':episode['ass_sha256'],
        'reference_sha256':episode['reference_sha256'],'result':args.result,
        'amount_seconds':args.amount_seconds,'notes':args.notes.strip(),
        'source':'user_playback_feedback','recorded_at_utc':datetime.now(timezone.utc).isoformat()}
    record['record_id']=fingerprint(record)[:20]
    path=ROOT/'calibration/playback-reviews.json'
    reviews=json.loads(path.read_text())if path.exists()else{'schema_version':1,'comment_cues':[],'records':[]}
    reviews['records'].append(record)
    path.write_text(json.dumps(reviews,ensure_ascii=False,indent=2)+'\n')
    write_outputs()
    print('Recorded actual feedback:',record['record_id'],'; timing maps and ASS files unchanged')

if __name__=='__main__':main()
