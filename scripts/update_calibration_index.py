"""Rebuild the review index from per-episode calibration manifests."""
from collections import Counter
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
LABELS={'user_validated_playback':'用户实播通过','visual_candidate_pending_playback':'独立画面候选，待实播',
    'estimated_equal_overlap_pending_playback':'均摊估算试播，待验证','uncalibrated_shortfall_preview':'缺口未解决，简单拼接试播',
    'nonstandard_parts_pending_content_alignment':'非标准长P，未生成播放版','needs_independent_anchors':'缺独立锚点'}

def main():
    records=[json.loads(p.read_text())for p in sorted((ROOT/'calibration').glob('S*/alignment.json'))]
    counts=Counter(d['status']for d in records)
    playable=[d for d in records if'ass'in d['artifacts']]
    comments=sum(sum(p['comments']for p in d['original_parts'])for d in playable)
    lines=['# 逐集校对留档\n',
        '此目录仅记录弹幕处理、公开参考图片、对应版本标识和校准测量。原视频、私人存储路径、设备连接信息、采集工具及原片截图不入库。\n',
        '播放核对请用[逐集试播验证清单](试播验证清单.md)：列出当前播放轴的片头、每个分P接点、重点区间与片尾检查时间，并保留验证状态及适用版本。\n',
        f'截至2026-10-29：{len(records)}个已收录正片投稿建立留档，{len(playable)}集有同视频主文件名的ASS，保留{comments:,}条正片命名P弹幕。用户实播通过{counts["user_validated_playback"]}集，独立旧CID画面候选{counts["visual_candidate_pending_playback"]}集，均摊估算{counts["estimated_equal_overlap_pending_playback"]}集，缺口试播{counts["uncalibrated_shortfall_preview"]}集，非标准长P待处理{counts["nonstandard_parts_pending_content_alignment"]}集。\n',
        '原合集缺失的8集没有生成空ASS；另发现的S04E09新投稿仅保存公开首帧和画面候选，尚未抓取新弹幕，未混入旧归档。\n',
        '|剧集|状态|正片/待辨认原始条数|排除条数|线索|校对记录与播放产物|\n|---|---|---:|---:|---|---|']
    for d in records:
        ep=d['episode'];source_count=sum(p['comments']for p in d['original_parts']);excluded=sum(p['comments']for p in d.get('excluded_parts',[]))
        notes=[]
        if d.get('estimation_model',{}).get('shortfall_unresolved'):
            notes.append(f'短{d["estimation_model"]["shortfall_seconds"]:.3f}秒，位置未测定')
        if d.get('cut_label_clues'):notes.append('名称有【删】，未实测')
        links=[f'[原始数据](../hacks-danmaku/{ep}/)',f'[映射及校验值]({ep}/alignment.json)']
        for role,label in [('naive_merged_xml','旧合并'),('aligned_xml','处理XML'),('ass','同名ASS')]:
            if role in d['artifacts']:
                path=d['artifacts'][role]['file'].removeprefix('calibration/')
                links.append(f'[{label}]({path})')
        lines.append(f'|{ep}|{LABELS.get(d["status"],d["status"])}|{source_count}|{excluded}|{"；".join(notes)or"—"}|'+ '、'.join(links)+'|')
    lines+=['\n## 留档内容与时间轴规则\n',
        '原始XML/PB沿用 `hacks-danmaku/<剧集>/`。清单关联原始CID、XML路径、SHA256及条数；新登记集同时逐包记录PB校验值。命名为0/1等不匹配剧集切片的P单列 `excluded_parts`，不加入正片累计时间；其原始数据与弹幕保留。非标准长P待辨认集则保留全部原始引用，暂不合并。',
        '\n`naive-merged.xml` 保存未经重叠处理的旧合并。`aligned.xml` 与同名ASS按该集清单状态理解：文件名中的aligned不代表已验证。原视频只记录发行文件名、时长、帧率、字节数和SHA256，以识别相同名称但内容不同的版本。',
        '\n无旧CID独立锚点的命名切片，按用户在2026-10-29指定规则试播：D=切片时长和−原片时长，o=max(D,0)/(n−1)，第i个P起点=前面片长和−(i−1)×o。D为负时保留简单拼接并标记缺口，不做负重叠或拉伸。最后一条弹幕只作为时长下界，不替代视频时长。',
        '\nS01E05、S01E08、S03E02、S05E03存在未解决的时长缺口。S03E02/S03E03/S05E03/S05E07的名称有【删】线索，具体区间仍未测定；总和较长也不能证明没有删减。S05E08、E09只有异常长P，未生成播放版，不能按长P时长压缩。\n',
        '## 独立画面与播放确认\n',
        'S01E01用户实播确认对应ASS SHA256为 `94cebd8db5e2b99254831da8f6ad9169fdbde121763b871dcfe1364fb8c8187e`，保留该版本。S01E03的P1落在4.004–4.963秒非唯一黑场，试播暂取4.004秒；其余P有独立候选，尚待实播确认。',
        '\n第一、三集P2–P6画面PTS间隔均为297.005041667秒；新S04E01/E09的长片段候选间隔约178秒，还有尾部约118秒间隔。新投稿的22张画面候选与旧CID对应关系尚未核实，另见[候选记录](../references/reuploads/visual-match-candidates.json)。未用新图直接修改旧弹幕映射。',
        '\n图像位置、分P首帧采样偏移、分P精确时长、真实重叠和用户播放体验分别记录；图片匹配本身不能证明采样偏移为零。逐接点比较与均摊值见[分P接点比较](分P接点比较.md)。\n',
        '## 重现与检查\n',
        'Python 3.9+标准库可执行 `python3 scripts/build_calibrated_episode.py <剧集> --check`，核对原始引用、旧合并和已生成XML/ASS。非标准长P只校验原始数据，保持映射待处理。',
        '\n新集可用 `scripts/register_calibration.py` 登记不含路径的发行标识和媒体测量；参数见 `--help`。拒绝覆盖已有校对记录，命名切片与排除P必须覆盖原目录。',
        '\n重建ASS需要Python 3.11+及[固定依赖](../requirements-calibration.txt)。执行 `python3 scripts/estimate_equal_overlap.py <剧集>` 重建估算/缺口试播，不覆盖画面对齐或非标准待处理集；`--playback-dir <已有本地目录>` 同步同名ASS，路径不写入清单。指定 `python3 scripts/build_calibrated_episode.py <剧集>` 可按已有映射重建。',
        '\n`python3 scripts/compare_part_intervals.py`、`python3 scripts/update_calibration_index.py` 重建接点对照与本索引；`python3 scripts/audit_first_frame_sources.py` 验证公开图片与来源。不读取原片，不联网。\n']
    (ROOT/'calibration/README.md').write_text('\n'.join(lines).rstrip()+'\n')
    from build_playback_checklist import write_outputs
    write_outputs()
    print(f'Indexed {len(records)} records, {len(playable)} playback files and {comments} named-part comments')

if __name__=='__main__':main()
