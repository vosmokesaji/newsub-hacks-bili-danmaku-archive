"""Register sanitized release identity and immutable source references for an episode."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('episode')
    ap.add_argument('--release',required=True,help='release basename only; no device path')
    ap.add_argument('--sha256',required=True)
    ap.add_argument('--size-bytes',required=True,type=int)
    ap.add_argument('--duration',required=True,type=float)
    ap.add_argument('--frame-rate',required=True)
    args=ap.parse_args()
    if not re.fullmatch(r'S\d{2}E\d{2}',args.episode):
        raise ValueError('Invalid episode identifier')
    if Path(args.release).name!=args.release or args.episode not in args.release:
        raise ValueError('Reference must be a matching release basename, without a path')
    if not re.fullmatch(r'[0-9a-f]{64}',args.sha256)or args.duration<=0 or args.size_bytes<=0:
        raise ValueError('Invalid reference fingerprint or media measurements')
    folder=ROOT/'calibration'/args.episode
    if folder.exists():
        raise ValueError('Refusing to overwrite existing calibration records')
    catalog=json.loads((ROOT/'hacks-danmaku/CID目录.json').read_text())
    post=next(e for e in catalog if re.search(r'\b'+args.episode+r'\b',e['title']))
    results=json.loads((ROOT/'hacks-danmaku/分段下载结果.json').read_text())
    downloads={r['cid']:r for r in results}
    named=[p for p in post['pages']if p['part'].startswith(args.episode+'-')]
    included=named or post['pages']
    def record(page):
        xml=ROOT/'hacks-danmaku'/downloads[page['cid']]['file']
        count=len(ET.parse(xml).getroot().findall('d'))
        if count!=downloads[page['cid']]['count']:
            raise ValueError('Original comment count mismatch')
        packages=sorted(xml.parent.glob(xml.stem+'.segment*.pb'))
        if not packages:
            raise ValueError('Original protobuf package missing')
        return {'cid':page['cid'],'part':page['part'],'page':page['page'],
            'archived_integer_duration_seconds':page['duration'],
            'file':str(xml.relative_to(ROOT)),'sha256':digest(xml),'comments':count,
            'protobuf_packages':[{'file':str(p.relative_to(ROOT)),'sha256':digest(p)}for p in packages]}
    parts=[record(p)for p in included]
    excluded=[{**record(p),'reason':'nonmatching numeric/other part label; not sequenced into this episode preview'}for p in post['pages']if p not in included]
    artifacts={}
    if named:
        naive=ROOT/'hacks-danmaku/merged'/f'{args.episode}.xml'
        if len(ET.parse(naive).getroot().findall('d'))!=sum(s['comments']for s in parts):
            raise ValueError('Naive merge/source count mismatch')
        folder.mkdir(parents=True)
        target=folder/'naive-merged.xml';shutil.copyfile(naive,target)
        artifacts['naive_merged_xml']={'file':str(target.relative_to(ROOT)),'sha256':digest(target)}
    else:
        folder.mkdir(parents=True)
    manifest={'schema_version':1,'episode':args.episode,'bvid':post['bvid'],
        'status':'needs_independent_anchors'if named else'nonstandard_parts_pending_content_alignment',
        'reference':{'release':args.release,'sha256':args.sha256,'size_bytes':args.size_bytes,
            'duration_seconds':args.duration,'frame_rate':args.frame_rate},
        'original_parts':parts,'excluded_parts':excluded,'mapping':None,'artifacts':artifacts,
        'anchor_status':{'public_first_frames':'no recovered old-CID first frames; see first-frame source survey','actual_overlap_seconds':None},
        'cut_label_clues':[{'cid':p['cid'],'part':p['part'],'status':'title clue only; cut interval unmeasured'}for p in post['pages']if'删'in p['part']],
        'limitations':['Original comments and their per-part timestamps are preserved unchanged',
            'No measured overlaps or cut intervals are inferred from total duration alone',
            'Reference records contain only release identity, duration and fingerprint; no device or storage paths']}
    if not named:
        manifest['limitations'].append('Only nonstandard long parts exist; no concatenation, scaling or playback ASS is generated until content identity is established')
    (folder/'alignment.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(args.episode,manifest['status'],sum(s['comments']for s in parts),'original comments registered; excluded',sum(s['comments']for s in excluded))

if __name__=='__main__':main()
