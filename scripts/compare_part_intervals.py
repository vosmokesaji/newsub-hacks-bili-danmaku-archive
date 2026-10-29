"""Compare measured image-anchor intervals; never impute unknown overlaps."""
from fractions import Fraction
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    observations=[]
    statuses=[]
    for path in sorted((ROOT/'calibration').glob('S*/alignment.json')):
        data=json.loads(path.read_text())
        statuses.append({'episode':data['episode'],'status':data['status'],'has_mapping':data.get('mapping')is not None})
        anchors=sorted(data.get('visual_matches',[]),key=lambda a:a['part'])
        for left,right in zip(anchors,anchors[1:]):
            if right['part']!=left['part']+1:
                continue
            base=Fraction(left['time_base'])
            if right['time_base']!=left['time_base']:
                raise ValueError('Timebase differs inside episode')
            value=(right['candidate_pts']-left['candidate_pts'])*base
            observations.append({'episode':data['episode'],'from_part':left['part'],'to_part':right['part'],
                'pts_delta':right['candidate_pts']-left['candidate_pts'],'time_base':left['time_base'],
                'seconds_exact':str(value),'seconds':float(value),'evidence':'matched candidate reference-image PTS; in-part sampling offsets unknown',
                'actual_overlap_seconds':None})
    values={Fraction(x['seconds_exact'])for x in observations}
    payload={'observed_anchor_intervals':observations,'all_observed_intervals_equal':len(values)==1 if observations else None,
             'episodes_with_visual_evidence':sorted({x['episode']for x in observations}),
             'episode_statuses':statuses,'actual_overlaps_equal':None,
             'limits':['Image-anchor spacing is not an overlap measurement','No inference is made for episodes without independent anchors','First-part trimming/black intervals are handled separately in each episode manifest']}
    out=ROOT/'calibration/part-interval-comparison.json'
    out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    lines=['# 分P接点间隔比较\n',
        '本表比较独立画面匹配得到的原片PTS间隔，不把整数分P时长差称为真实重叠。首帧在各P内的采样偏移及各P精确片长尚未测定，因此“真实交叉时间是否一致”仍为未知。\n',
        '|剧集|接点|候选画面间隔（秒）|PTS差（时间基1/24000）|\n|---|---|---:|---:|']
    for x in observations:
        lines.append(f'|{x["episode"]}|P{x["from_part"]}→P{x["to_part"]}|{x["seconds"]:.9f}|{x["pts_delta"]}|')
    lines+=['\n现有观测：第一集与第三集P2–P6的各间隔相同，均为297.005041667秒／7121帧。仅对这些观测成立，不能据此称所有集都按同一交叉时长切片。',
            '\n第三集P1参考图片落在约4–5秒的非唯一黑场，而第一集试播P1暂按0秒且已获用户播放确认。这说明首P至少要独立处理；详见各集清单。',
            '\n## 各集处理状态\n','|剧集|状态|\n|---|---|']
    labels={'user_validated_playback':'用户实播通过（测量限制保留）','visual_candidate_pending_playback':'独立画面候选，待实播；P1单独保留不确定区间','needs_independent_anchors':'原始与旧合并已留档，缺独立锚点，未生成校准ASS'}
    for x in statuses:
        lines.append(f'|{x["episode"]}|{labels.get(x["status"],x["status"])}|')
    (ROOT/'calibration/分P接点比较.md').write_text('\n'.join(lines).rstrip()+'\n')
    print(f'Compared {len(observations)} independently observed anchor intervals; true overlaps remain unmeasured.')

if __name__=='__main__':main()
