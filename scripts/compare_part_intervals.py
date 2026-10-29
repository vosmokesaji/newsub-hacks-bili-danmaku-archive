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
        statuses.append({'episode':data['episode'],'status':data['status'],'has_mapping':data.get('mapping')is not None,'estimation_model':data.get('estimation_model')})
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
    labels={'user_validated_playback':'用户实播通过（测量限制保留）','visual_candidate_pending_playback':'独立画面候选，待实播；P1单独保留不确定区间','needs_independent_anchors':'缺独立锚点','estimated_equal_overlap_pending_playback':'按用户规则均摊多出时长的估算试播，待验证','uncalibrated_shortfall_preview':'总和短于原片，保留简单拼接试播，缺口未解决','nonstandard_parts_pending_content_alignment':'非标准长P，待确认内容；未生成播放版'}
    for x in statuses:
        lines.append(f'|{x["episode"]}|{labels.get(x["status"],x["status"])}|')
    lines+=['\n## 按用户指定规则生成的估算值\n',
        '2026-10-29用户明确要求：切片总时长多于原片时，将多出部分平均分到相邻接点。此处使用存档分P时长；末条弹幕仅为视频时长下界，不当作实际片长。估算值因片头片尾、版本差异、删减与整数取整而可能失真，不能用来证明真实重叠。',
        '\n第一、三集保留独立画面映射，不用均摊模型覆盖。总和短于原片时不产生负重叠、不拉伸，保留简单拼接试播并标记缺口未解决。\n',
        '|剧集|切片和−原片（秒）|接点数|每接点分配值（秒）|处理|\n|---|---:|---:|---:|---|']
    for x in statuses:
        m=x['estimation_model']
        if m:
            lines.append(f'|{x["episode"]}|{m["source_sum_minus_reference_seconds"]:+.6f}|{m["join_count"]}|{m["estimated_overlap_per_join_seconds"]:.6f}|{"缺口未解决，简单拼接"if m["shortfall_unresolved"]else "均摊差值试播，未实测"}|')
    lines.append('\n按这个分配模型，每集算出的值并不完全相同。这既不证明实际重叠不同，也不证明存在真实变速或删减；需与画面证据和实播反馈分开记录。\n')
    new_refs=ROOT/'references/reuploads/visual-match-candidates.json'
    if new_refs.exists():
        new=json.loads(new_refs.read_text())
        payload['new_upload_visual_candidates_file']='references/reuploads/visual-match-candidates.json'
        payload['new_upload_intervals_excluded_from_old_cid_observations']=True
        out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
        lines+=['## 新投稿的独立画面候选（与旧CID分开）\n',
            'S04E01、S04E09新投稿中22张非片头首帧在对应完整原片中找到高相似画面候选；两个首P为重复片头标志，未强行指定唯一起点。下表属于新CID，尚未验证与旧分P的对应关系，不用于改写旧弹幕映射。详情与原始PTS见[画面候选记录](../references/reuploads/visual-match-candidates.json)。\n',
            '|剧集|新分P接点|画面PTS间隔（秒）|\n|---|---|---:|']
        for interval in new['observed_new_image_intervals']:
            lines.append(f'|{interval["episode"]}|{interval["from_new_part"]}→{interval["to_new_part"]}|{interval["seconds"]:.9f}|')
        lines.append('\n181秒显示时长的长片段，其相邻图像间隔约178秒、存在一帧差异；新投稿尾部较短片段还出现约118秒间隔。第一、三集约297秒的图像间隔不适用于这些新投稿。以上仍不是原分P精确片长或真实重叠测量。\n')
    (ROOT/'calibration/分P接点比较.md').write_text('\n'.join(lines).rstrip()+'\n')
    print(f'Compared {len(observations)} independently observed anchor intervals; true overlaps remain unmeasured.')

if __name__=='__main__':main()
