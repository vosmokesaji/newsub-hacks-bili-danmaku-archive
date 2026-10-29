"""Build version-aware, concrete playback checks from archived timing maps."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
LABELS={'user_validated_playback':'整集已有实播确认','visual_candidate_pending_playback':'独立画面候选，待实播',
    'estimated_equal_overlap_pending_playback':'均摊估算试播','uncalibrated_shortfall_preview':'缺口未解决，简单拼接试播',
    'nonstandard_parts_pending_content_alignment':'非标准长P，暂无播放版','needs_independent_anchors':'尚无播放映射'}
RESULTS={'pass':'通过','early':'弹幕偏早','late':'弹幕偏晚','inconsistent':'偏差不一致','cannot_judge':'无法判断'}

def sha(body):
    return hashlib.sha256(body).hexdigest()

def fingerprint(value):
    return sha(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())

def load(path):
    return json.loads(path.read_text())

def time_text(value,precise=True):
    value=max(0,value)
    ticks=int(math.floor(value*1000+.5)) if precise else int(math.floor(value))
    seconds=ticks//1000 if precise else ticks
    h,m,s=seconds//3600,seconds//60%60,seconds%60
    prefix=f'{h:02d}:'if h else''
    return prefix+f'{m:02d}:{s:02d}'+(f'.{ticks%1000:03d}'if precise else'')

def window_text(start,end):
    return time_text(math.floor(start),False)+'–'+time_text(math.ceil(end),False)

def clean(text,limit=44):
    value=' '.join((text or'').split())
    if len(value)>limit:value=value[:limit]+'…'
    return value.replace('|','\\|').replace('\n',' ').replace('`','ˋ').replace('<','＜').replace('>','＞')

def episode_version(data):
    """Only playback-affecting identity; status/feedback/date never invalidate a review."""
    return fingerprint({'ass_sha256':data.get('artifacts',{}).get('ass',{}).get('sha256'),
        'reference_sha256':data['reference']['sha256'],'reference_duration':data['reference']['duration_seconds'],
        'mapping':[{'cid':p['cid'],'offset':p['preview_offset_seconds']}for p in data.get('mapping')or[]],
        'sources':[{'cid':p['cid'],'sha256':p['sha256']}for p in data['original_parts']]})

def review_state(records,episode,version,point=None):
    individual=[r for r in records if r['episode']==episode and r.get('checkpoint_id')==point['id']]if point else[]
    current=[r for r in individual if r.get('checkpoint_version')==point['version']]
    if current:return {'state':'current_point_record','record':current[-1]}
    if individual:return {'state':'stale_point_record','record':individual[-1]}
    whole=[r for r in records if r['episode']==episode and r['scope']=='episode']
    valid=[r for r in whole if r.get('episode_version')==version]
    if valid:return {'state':'current_episode_record_point_not_individually_reviewed','record':valid[-1]}
    if whole:return {'state':'stale_episode_record','record':whole[-1]}
    return {'state':'pending','record':None}

def review_text(review,whole=False):
    state=review['state'];record=review.get('record')
    if state=='pending':return'待验证'
    if state.startswith('stale_'):return'旧记录保留，当前版本待复验'
    label=RESULTS[record['result']]
    if record.get('amount_seconds')is not None:label+=f'约{record["amount_seconds"]:g}秒'
    if state=='current_episode_record_point_not_individually_reviewed':
        return label+'（整集体验，未逐点打卡）'if whole else'整集反馈：'+label+'；本点未单独记录'
    return label

def build_data(root=ROOT):
    inputs={}
    def read(relative):
        path=root/relative;body=path.read_bytes();inputs[relative]=sha(body)
        return json.loads(body)
    catalog=read('hacks-danmaku/CID目录.json')
    pages={p['cid']:p for e in catalog for p in e['pages']}
    reviews_path=root/'calibration/playback-reviews.json'
    reviews=read('calibration/playback-reviews.json')if reviews_path.exists()else{'schema_version':1,'comment_cues':[],'records':[]}
    records=reviews['records'];episodes=[]
    for path in sorted((root/'calibration').glob('S*/alignment.json')):
        relative=str(path.relative_to(root));data=read(relative);ep=data['episode'];duration=data['reference']['duration_seconds']
        version=episode_version(data)
        entry={'episode':ep,'bvid':data['bvid'],'status':data['status'],'label':LABELS.get(data['status'],data['status']),
            'manifest':relative,'duration_seconds':duration,'episode_version':version,
            'ass_sha256':data.get('artifacts',{}).get('ass',{}).get('sha256'),
            'reference_sha256':data['reference']['sha256'],'checkpoints':[],
            'estimation_model':data.get('estimation_model'),'has_cut_label':any('删'in pages[s['cid']]['part']for s in data['original_parts']),
            'whole_episode_feedback':review_state(records,ep,version)}
        if data['status']=='user_validated_playback'and entry['whole_episode_feedback']['state']!='current_episode_record_point_not_individually_reviewed':
            entry['label']='原留档标记实播确认；当前版本待复验'
        if not data.get('mapping')or not entry['ass_sha256']:
            entry['playback_available']=False;episodes.append(entry);continue
        ass_path=root/data['artifacts']['ass']['file']
        if sha(ass_path.read_bytes())!=entry['ass_sha256']:raise ValueError('ASS checksum mismatch: '+ep)
        inputs[data['artifacts']['ass']['file']]=entry['ass_sha256']
        entry['playback_available']=True;entry['ass_file']=data['artifacts']['ass']['file']
        maps={m['cid']:m for m in data['mapping']};parts=[]
        for ordinal,source in enumerate(data['original_parts'],1):
            body=(root/source['file']).read_bytes()
            if sha(body)!=source['sha256']:raise ValueError('Original XML checksum mismatch: '+ep)
            inputs[source['file']]=source['sha256'];page=pages[source['cid']];mapping=maps[source['cid']]
            comments=[]
            for row in ET.fromstring(body).findall('d'):
                fields=row.attrib['p'].split(',');local=float(fields[0])
                comments.append({'id':fields[7],'source_seconds':local,'playback_seconds':local+mapping['preview_offset_seconds'],'text':row.text or''})
            comments.sort(key=lambda x:(x['source_seconds'],x['id']))
            parts.append({'cid':source['cid'],'original_page':page['page'],'part_title':page['part'],'episode_part_ordinal':ordinal,
                'start':mapping['preview_offset_seconds'],'duration':page['duration'],'comments':comments})
        # ASS stores centiseconds. Verify the full timing multiset against the
        # mapping, then use actual emitted starts for the quoted comment cues.
        ass_starts=[]
        for line in ass_path.read_text(encoding='utf-8-sig').splitlines():
            if line.startswith('Dialogue:'):
                h,m,s=line.split(',',3)[1].split(':')
                ass_starts.append(int(h)*3600+int(m)*60+float(s))
        projected=sorted((c for part in parts for c in part['comments']),key=lambda c:(c['playback_seconds'],c['id']))
        ass_starts.sort()
        if len(projected)!=len(ass_starts)or any(abs(c['playback_seconds']-t)>.011 for c,t in zip(projected,ass_starts)):
            raise ValueError('ASS event times do not match the archived map: '+ep)
        for comment,emitted_time in zip(projected,ass_starts):
            comment['mapped_seconds']=comment['playback_seconds'];comment['playback_seconds']=emitted_time
        shortfall=bool((data.get('estimation_model')or{}).get('shortfall_unresolved'))
        entry['priority']='优先：时长缺口'if shortfall else'优先：名称有删减线索'if entry['has_cut_label']else'回归参考'if data['status']=='user_validated_playback'else'常规'
        def point(identifier,kind,center,start,end,reason,part=None,samples=None):
            start=max(0,min(start,duration));end=max(start,min(end,duration))
            result={'id':ep+'-'+identifier,'kind':kind,'center_seconds':center,'watch_start_seconds':start,
                'watch_end_seconds':end,'reason':reason,'part':({k:v for k,v in part.items()if k!='comments'}if part else None),
                'comment_samples':samples or[]}
            if any(p['id']==result['id']for p in entry['checkpoints']):
                raise ValueError('Duplicate playback checkpoint: '+result['id'])
            if any(not 0<=c['playback_seconds']<duration for c in result['comment_samples']):
                result['reason']+='注意：示例在影片时间范围之外，应先复查映射，不能在当前视频内判为通过。'
            result['version']=fingerprint({'episode_version':version,'id':result['id'],'kind':kind,
                'center':center,'watch_range':[start,end],'cid':part['cid']if part else None,
                'comment_samples':[{'id':c['id'],'playback_seconds':c['playback_seconds']}for c in result['comment_samples']]})
            result['review']=review_state(records,ep,version,result);entry['checkpoints'].append(result)
        first=parts[0];sample=first['comments'][:1]
        intro_end=max(60,sample[0]['playback_seconds']+8 if sample else 60)
        reason='检查第一条可辨认弹幕是否对应当前画面，确认片头整体偏移。'
        ambiguity=maps[first['cid']].get('candidate_image_interval_seconds')
        if ambiguity and ambiguity[1]>ambiguity[0]:
            reason+=f'首P当前偏移{first["start"]:.3f}秒，图像候选区间{ambiguity[0]:.3f}–{ambiguity[1]:.3f}秒并不唯一；重点看片头后第一段剧情。'
            entry['intro_ambiguity_seconds']=ambiguity
            if entry['priority']=='常规':entry['priority']='优先：首P不确定'
        if first['original_page']!=1:reason+=f'首个正片是原P{first["original_page"]}，前面的占位P已排除。'
        point('I','intro',first['start'],0,intro_end,reason,first,sample)
        for index,part in enumerate(parts[1:],1):
            first_comment=part['comments'][:1];center=part['start'];end=center+45
            reason=f'原P{parts[index-1]["original_page"]}→原P{part["original_page"]}；观察接点前后偏差是否改变、是否逐P累积。'
            if first_comment and first_comment[0]['playback_seconds']>end:
                end=first_comment[0]['playback_seconds']+8;reason+='新P首条弹幕较晚，观看窗口已延长至其入场后。'
            if not first_comment:reason+='该P无原始弹幕，不能仅靠没有弹幕判为通过。'
            point(f'J{index:02d}','join',center,center-15,end,reason,part,first_comment)
        if shortfall:
            for part in parts:
                middle=min(part['start']+part['duration']/2,duration)
                sample=sorted(part['comments'],key=lambda x:abs(x['playback_seconds']-middle))[:1]
                point(f'M{part["episode_part_ordinal"]:02d}','shortfall_midpart',middle,middle-30,middle+30,
                    '时长缺口位置未知；检查P中部是否已出现不同偏差，并与本P前后接点比较。抽查不能排除段内其他剪辑。',part,sample)
                if part['comments']:
                    tail=part['comments'][-1]
                    point(f'L{part["episode_part_ordinal"]:02d}','shortfall_part_tail',tail['playback_seconds'],tail['playback_seconds']-10,tail['playback_seconds']+8,
                        '检查本P最后一条弹幕，与P首和中部比较；定位偏差是段内改变还是接点改变。',part,[tail])
        for part in parts:
            if'删'in part['part_title']:
                point(f'C{part["episode_part_ordinal"]:02d}','cut_label_span',part['start'],part['start'],part['start']+part['duration'],
                    '整段留意偏差突变；此范围是标题带【删】P按当前映射和存档片长的大致覆盖，含接点重叠，不是测定的删减范围。',part,part['comments'][:1])
        all_comments=[x for part in parts for x in part['comments']]
        final=max(all_comments,key=lambda x:x['playback_seconds'])if all_comments else None
        point('T','episode_tail',duration,max(0,duration-90),duration,
            '检查最后90秒及最后一条原始弹幕，判断后半集是否累积偏移；不能把总时长缺口直接定位到片尾。',parts[-1],[final]if final else[])
        for index,cue in enumerate([c for c in reviews.get('comment_cues',[])if c['episode']==ep],1):
            part=next((p for p in parts if p['cid']==cue['cid']),None)
            comment=next((c for c in part['comments']if c['id']==cue['comment_id']),None)if part else None
            if comment is None:raise ValueError('Pinned source comment disappeared: '+ep)
            center=comment['playback_seconds']
            point(cue.get('checkpoint_suffix',f'Q{index:02d}'),'comment_cue',center,center-10,center+15,
                cue['reason']+' 原观众可能反应滞后；该入场时间不能直接当作剧情发生时间。',part,[comment])
        entry['part_starts']=[{k:v for k,v in p.items()if k!='comments'}for p in parts]
        episodes.append(entry)
    new_path=root/'references/reuploads/visual-match-candidates.json';new_posts=[]
    if new_path.exists():
        new=read('references/reuploads/visual-match-candidates.json')
        for post in new['posts']:
            candidates=[]
            for anchor in post['anchors']:
                if anchor.get('candidate_pts')is None:continue
                candidates.append({'part':anchor['new_part'],'cid':anchor['new_cid'],'seconds':anchor['candidate_time_seconds'],
                    'image_file':anchor['reference_image_file'],'image_sha256':anchor['reference_image_sha256'],'score':anchor['combined_score']})
            current=next((e for e in episodes if e['episode']==post['episode']and e['playback_available']),None)
            relation='暂无当前ASS'if not current else'同当前ASS投稿；画面仍是候选'if current['bvid']==post['new_bvid']else'与当前ASS投稿不同；旧CID对应未核实'
            new_posts.append({'episode':post['episode'],'bvid':post['new_bvid'],'candidates':candidates,'current_ass_relation':relation,
                'usable_for_old_ass_validation':False})
    expected={f'S{s:02d}E{e:02d}'for s,n in[(1,10),(2,8),(3,9),(4,10),(5,10)]for e in range(1,n+1)}
    catalogue_episodes={m.group()for e in catalog if(m:=re.search(r'S\d{2}E\d{2}',e['title']))}
    missing=sorted(expected-catalogue_episodes)
    checkpoints=[p for e in episodes for p in e['checkpoints']]
    return {'schema_version':1,'input_files':inputs,'input_fingerprint':fingerprint(inputs),
        'basis':'Current ASS playback timeline; estimated checkpoints are not measured overlaps or edit locations',
        'episodes':episodes,'missing_original_catalogue_episodes':missing,
        'unregistered_catalogue_episodes':sorted(catalogue_episodes-{e['episode']for e in episodes}),'new_upload_picture_checks':new_posts,
        'summary':{'registered_episodes':len(episodes),'episodes_with_ass':sum(e['playback_available']for e in episodes),
            'playback_checkpoints':len(checkpoints),'current_individually_passed_points':sum(p['review']['state']=='current_point_record'and p['review']['record']['result']=='pass'for p in checkpoints),
            'point_review_states':dict(Counter(p['review']['state']for p in checkpoints)),
            'new_upload_picture_candidates':sum(len(p['candidates'])for p in new_posts)}}

def sample_text(point):
    if not point['comment_samples']:return'无可用原始弹幕示例，保持无法据此判断'
    return'；'.join(f'{time_text(c["playback_seconds"])}「{clean(c["text"])}」'for c in point['comment_samples'])

def render(data):
    priority_episodes=sorted((e for e in data['episodes']if e['playback_available']and e['priority'].startswith('优先')),key=lambda e:(0 if(e.get('estimation_model')or{}).get('shortfall_unresolved')else 1,e['episode']))
    lines=['# 逐集试播验证清单\n',
        f'本页从当前映射、原始弹幕和ASS自动生成；依据指纹 `{data["input_fingerprint"][:16]}`。共{data["summary"]["episodes_with_ass"]}集有ASS、{data["summary"]["playback_checkpoints"]}个播放检查点。\n',
        '所有时间均为完整视频播放器的时间；示例弹幕时间已核对当前ASS的实际入场时间。估算集的接点仍是估算位置，显示毫秒仅用于找准当前文件，不表示剪辑点已精确测量。观看范围向外取整到秒，末尾以影片实际结束为准。\n',
        '## 怎样检查与反馈\n',
        '1. 每集先看片头，再依次看接点窗口，最后看末90秒。四集时长缺口还需看每P中部和末条弹幕；带【删】P要整段留意。',
        '2. 选择能对应动作或台词的弹幕比较，记录是“早约2秒”“晚约3秒”还是“前段正常、从某点开始变晚”。原观众也可能反应迟，单条“哈哈/谢谢”只能用于找位置，不能据此确认同步。',
        '3. 反馈可直接写：`S03E02-J02，09:01附近，弹幕晚约2秒，从这里开始变化；弹幕原句：……`。这是格式示例，不是该点已有问题。检查ID随文中各行列出。',
        '4. 通过记录绑定原片、当前ASS和映射版本。改轴或换文件后，旧记录保留并标为待复验；仅登记反馈/改变进度状态不会让同一版本的记录失效。整集认可与逐点检查分开，抽查通过不证明全片每一处都同步。\n',
        f'建议先核对下面{len(priority_episodes)}集重点；其余集正常观看到接点时留意即可。完整列表保留所有位置，方便发现问题后追查从哪一段开始变化。\n',
        '## 优先顺序与重点时间\n','|剧集|优先原因|当前重点时间|\n|---|---|---|']
    for ep in priority_episodes:
        cuts=[p for p in ep['checkpoints']if p['kind']=='cut_label_span']
        notes=[window_text(p['watch_start_seconds'],p['watch_end_seconds'])+'（带删字P整段）'for p in cuts]
        if not notes:
            notes=['接点：'+'、'.join(time_text(p['center_seconds'])for p in ep['checkpoints']if p['kind']=='join')]
        if ep.get('intro_ambiguity_seconds'):
            intro=next(p for p in ep['checkpoints']if p['kind']=='intro')
            join=next((p for p in ep['checkpoints']if p['kind']=='join'),None)
            notes=[window_text(intro['watch_start_seconds'],intro['watch_end_seconds'])+'（首P图像非唯一）'+('；'+time_text(join['center_seconds'])+'起各接点'if join else'')]
        if(ep.get('estimation_model')or{}).get('shortfall_unresolved'):
            notes.append(f'总差约{ep["estimation_model"]["shortfall_seconds"]:.3f}秒，位置未知；每P首/中/尾都查')
        lines.append(f'|[{ep["episode"]}](#{ep["episode"].lower()})|{ep["priority"]}|'+ '；'.join(notes)+'|')
    lines+=['\n## 各集接点速查\n','接点表示下一个正片切片在当前ASS中的起点；原P编号可能跳过占位P。每个接点默认从前15秒看到后45秒，详细行还给出真实弹幕入场位置。\n',
        '|剧集|当前处理|接点时间（播放器时间）|\n|---|---|---|']
    for ep in data['episodes']:
        if not ep['playback_available']:continue
        times='、'.join(time_text(p['center_seconds'])for p in ep['checkpoints']if p['kind']=='join')or'无接点'
        lines.append(f'|[{ep["episode"]}](#{ep["episode"].lower()})|{ep["label"]}|{times}|')
    lines+=['\n## 逐集检查\n']
    names={'intro':'片头','join':'接点','shortfall_midpart':'P中部','shortfall_part_tail':'P末条','cut_label_span':'带删字P整段','episode_tail':'片尾','comment_cue':'可辨认弹幕'}
    for ep in data['episodes']:
        if not ep['playback_available']:continue
        lines += [f'### {ep["episode"]}\n',
            f'当前：{ep["label"]}；片长{time_text(ep["duration_seconds"])}；ASS版本 `{ep["ass_sha256"][:12]}`。整集反馈：{review_text(ep["whole_episode_feedback"],whole=True)}。',
            f'\n[校对依据]({ep["episode"]}/alignment.json) · [当前ASS]({ep["ass_file"].removeprefix("calibration/")})\n',
            '|检查ID / 类型|建议观看范围|重点位置与实际弹幕|当前记录|\n|---|---|---|---|']
        for point in ep['checkpoints']:
            part=point['part'];label=f'原P{part["original_page"]} / {clean(part["part_title"])}'if part else''
            detail=f'{time_text(point["center_seconds"])}，{label}。{point["reason"]} 弹幕入场：{sample_text(point)}'
            lines.append(f'|{point["id"]} / {names[point["kind"]]}|{window_text(point["watch_start_seconds"],point["watch_end_seconds"])}|{detail}|{review_text(point["review"])}|')
        lines.append('')
    lines+=['\n## 暂无归档播放版的集数\n']
    blocked=[e for e in data['episodes']if not e['playback_available']]
    for ep in blocked:lines.append(f'- {ep["episode"]}：{ep["label"]}。原始弹幕保留，暂无可靠播放映射，不列假定的接点。')
    if not blocked:lines.append('已登记的集数均有播放版。')
    if data['unregistered_catalogue_episodes']:
        lines.append('\n目录已收录但尚未建立逐集播放记录：'+'、'.join(data['unregistered_catalogue_episodes'])+'。')
    lines+=['\n当前目录缺失：'+ ('、'.join(data['missing_original_catalogue_episodes'])or'无')+'。缺失集不生成空ASS；另发现的新投稿与当前ASS的关系见下节。\n',
        '## 独立画面核对：不替代弹幕实播\n',
        '下列时间用于检查参考图片是否对应原片画面，投稿与当前ASS的关系单列。不同CID的对应不能直接认定；核对图片正确也不等于弹幕接点通过，这些点不参与上面播放通过数。重复片头标志没有唯一候选时，不强行列时间。\n',
        '|剧集 / 新投稿|与当前ASS的关系|新分P|原片候选时间|公开参考图片|\n|---|---|---|---:|---|']
    for post in data['new_upload_picture_checks']:
        for point in post['candidates']:
            lines.append(f'|{post["episode"]} / {post["bvid"]}|{post["current_ass_relation"]}|{point["part"]}|{time_text(point["seconds"])}|[参考图](../{point["image_file"]})|')
    lines+=['\n## 更新与留档\n',
        '本页及 `playback-checklist.json` 由 `python3 scripts/build_playback_checklist.py` 生成；`--check` 检查是否与当前依据一致。不要手改生成的时间。ASS重建、校对索引更新和首帧来源报告更新后会同步重建本页。',
        '\n人工反馈保存在 `playback-reviews.json`，重建不会清空记录。可用 `scripts/record_playback_review.py` 按检查ID登记，或按整集登记；参数见 `--help`。反馈只记录观看结果，不自动改时间轴，也不把估算提升为实测。',
        '\n“实时更新”随本项目的校准/反馈处理流程完成，无需重新抄写时间表；若直接手改映射数据，应立即重新生成并执行 `--check`。原视频、原片截图、存储路径和连接配置不进入这些文件。\n']
    return'\n'.join(lines).rstrip()+'\n'

def write_outputs(root=ROOT,check=False):
    data=build_data(root);outputs={root/'calibration/playback-checklist.json':json.dumps(data,ensure_ascii=False,indent=2)+'\n',
        root/'calibration/试播验证清单.md':render(data)}
    for path,body in outputs.items():
        if check:
            if not path.exists()or path.read_text()!=body:raise ValueError('Playback checklist is stale: '+str(path.relative_to(root)))
        else:path.write_text(body)
    return data

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');args=parser.parse_args()
    data=write_outputs(check=args.check)
    print(('Verified'if args.check else'Updated')+f' playback checklist: {data["summary"]["episodes_with_ass"]} episodes, {data["summary"]["playback_checkpoints"]} checks')

if __name__=='__main__':main()
