"""User-requested excess-duration sharing for explicitly unverified previews."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
ELIGIBLE={'needs_independent_anchors','estimated_equal_overlap_pending_playback','uncalibrated_shortfall_preview'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('episodes',nargs='*')
    parser.add_argument('--playback-dir',type=Path,help='optional local directory for same-name ASS; never stored in manifests')
    args=parser.parse_args()
    paths=sorted((ROOT/'calibration').glob('S*/alignment.json'))
    if args.episodes:
        paths=[p for p in paths if p.parent.name in args.episodes]
        if len(paths)!=len(set(args.episodes)):
            raise ValueError('Unknown episode requested')
    catalog=json.loads((ROOT/'hacks-danmaku/CID目录.json').read_text())
    for path in paths:
        data=json.loads(path.read_text())
        if data['status']not in ELIGIBLE:
            print(data['episode'],': keeping existing status and mapping unchanged')
            continue
        ep=next(e for e in catalog if e['bvid']==data['bvid'])
        named=[p for p in ep['pages'] if p['cid']in {s['cid']for s in data['original_parts']} and p['part'].startswith(data['episode']+'-')]
        included={p['cid']for p in named}
        excluded={p['cid']for p in data.get('excluded_parts',[])}
        if included&excluded or included|excluded!={p['cid']for p in ep['pages']}:
            raise ValueError('All catalogue parts must be explicitly included or excluded')
        if included!={p['cid']for p in data['original_parts']}:
            raise ValueError('Only matching named episode slices may enter this estimator')
        if any(p['part'].startswith(data['episode']+'-')for p in ep['pages']if p['cid']in excluded):
            raise ValueError('Named episode slices cannot be silently excluded')
        if len(named)<2:
            raise ValueError('Uniform adjacent-overlap estimation requires at least two parts')
        duration=Decimal(str(data['reference']['duration_seconds']))
        source_sum=sum(Decimal(p['duration'])for p in named)
        delta=source_sum-duration
        joins=len(named)-1
        overlap=delta/joins if delta>0 and joins else Decimal(0)
        if overlap>=min(Decimal(p['duration'])for p in named):
            raise ValueError('Estimated overlap is inconsistent with part lengths')
        mapping=[];elapsed=Decimal(0)
        source_by_cid={s['cid']:s for s in data['original_parts']}
        for i,p in enumerate(named):
            raw=ET.parse(ROOT/source_by_cid[p['cid']]['file']).getroot().findall('d')
            times=[Decimal(x.attrib['p'].split(',')[0])for x in raw]
            mapping.append({'part':p['page'],'cid':p['cid'],'source_comments':len(raw),
                'archived_integer_duration_seconds':p['duration'],
                'last_comment_seconds_lower_bound':str(max(times))if times else None,
                'preview_offset_seconds':float(elapsed-overlap*i),
                'offset_status':'user_requested_equal_excess_duration_estimate'if delta>=0 else 'unadjusted_naive_offset_shortfall_unresolved',
                'estimated_overlap_with_previous_seconds':float(overlap)if i else None,
                'actual_part_duration_seconds':None,'verified_overlap_seconds':None})
            elapsed+=Decimal(p['duration'])
        data['status']='estimated_equal_overlap_pending_playback'if delta>=0 else 'uncalibrated_shortfall_preview'
        data['mapping']=mapping
        data['estimation_model']={
            'method':'share_positive_archived_duration_excess_equally_across_joins',
            'requested_by':'user on 2026-10-29',
            'duration_basis':'archived integer-second part durations, not the last comment time',
            'source_sum_seconds':float(source_sum),'reference_seconds':float(duration),
            'source_sum_minus_reference_seconds':float(delta),'join_count':joins,
            'estimated_overlap_per_join_seconds':float(overlap),
            'formula':'D=sum(d_i)-T; o=max(D,0)/(n-1); start_i=sum(d_j for j<i)-(i-1)*o',
            'shortfall_unresolved':delta<0,
            'shortfall_seconds':float(-delta)if delta<0 else 0,
            'raw_comment_tail_is_only_lower_bound':True,
            'comparison_to_measured_image_intervals':'not established for this episode',
            'actual_overlap_seconds':None,
        }
        data['assumptions']=['first part starts at reference zero (unverified)',
            'each part has no unmeasured internal edits or speed change',
            'positive excess attributed entirely to identical adjacent overlaps, per user-selected preview model']
        data['limits']=['This is a requested timing estimate, not independent visual calibration or playback confirmation',
            'Part-duration rounding, intro/outro differences, edits and version differences can invalidate uniform sharing',
            'Last comment timestamps are lower bounds only; no negative overlap or forced stretching is applied for shortfalls']
        data['xml_comment']='ESTIMATED PREVIEW: uniform sharing of positive archived-duration excess, requested by user. Not measured overlaps. Shortfall episodes retain naive timing and unresolved content/version differences.'
        data['ass_style']=json.loads((ROOT/'calibration/S01E01/alignment.json').read_text())['ass_style']
        path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
        original_argv=sys.argv
        try:
            sys.argv=['build_calibrated_episode.py',data['episode']]
            runpy.run_path(str(ROOT/'scripts/build_calibrated_episode.py'),run_name='__main__')
        finally:
            sys.argv=original_argv
        data=json.loads(path.read_text())
        ass_path=ROOT/data['artifacts']['ass']['file']
        if args.playback_dir:
            if not args.playback_dir.is_dir():
                raise ValueError('Playback directory must already exist')
            target=args.playback_dir/ass_path.name
            if target.exists() and target.read_bytes()!=ass_path.read_bytes():
                folder=args.playback_dir/'.ass-backups';folder.mkdir(exist_ok=True)
                sha=hashlib.sha256(target.read_bytes()).hexdigest()[:12]
                backup=folder/(target.stem+'.'+sha+'.ass')
                if not backup.exists():shutil.copyfile(target,backup)
            temporary=target.with_suffix('.ass.tmp')
            shutil.copyfile(ass_path,temporary);temporary.replace(target)
        print(data['episode'],data['status'],'join estimate:',float(overlap),'seconds')

if __name__=='__main__':main()
