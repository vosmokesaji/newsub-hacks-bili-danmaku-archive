"""Offline verification and report for public first-frame evidence coverage."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def main():
    data=json.loads((ROOT/'processing/first-frame-sources.json').read_text())
    catalog=json.loads((ROOT/'hacks-danmaku/CID目录.json').read_text())
    by_bvid={e['bvid']:e for e in catalog}
    rows=data['results']
    if len(rows)!=len(by_bvid) or {r['bvid']for r in rows}!=set(by_bvid):
        raise ValueError('Source survey does not match archived post catalogue')
    count=0
    for row in rows:
        ep=by_bvid[row['bvid']]
        if row['catalogue_part_count']!=len(ep['pages']):
            raise ValueError('Part-count mismatch')
        cids={p['cid']for p in ep['pages']}
        images=row.get('images',[])
        if row['first_frame_count']!=len(images):
            raise ValueError('Image count mismatch')
        for image in images:
            path=(ROOT/image['file']).resolve()
            if ROOT not in path.parents or image['cid']not in cids:
                raise ValueError('Invalid public evidence reference')
            if hashlib.sha256(path.read_bytes()).hexdigest()!=image['sha256']:
                raise ValueError('Public image checksum mismatch')
            count+=1
        if row.get('last_query_http_status')==429 and row['status']!='rate_limited_pending_verification':
            raise ValueError('HTTP429 must not be treated as no snapshot')
        if row['status']=='canonical_query_no_snapshot'and row.get('last_successful_query_http_status')!=200:
            raise ValueError('No-snapshot finding needs a successful response')
    summary=data['summary']
    if count!=summary['saved_first_frame_images'] or dict(Counter(r['status']for r in rows))!=summary['status_counts']:
        raise ValueError('Survey totals mismatch')
    audit=data['original_snapshot_audit']
    if 'first_frame'in audit['collection_pages_field_names']:
        raise ValueError('Update the scope explanation: collection now contains first_frame')
    if any(not x['json_path'].startswith('/videoData/pages/')for x in audit['first_frame_fields']):
        raise ValueError('Update the scope explanation: first_frame exists outside current episode')
    labels={'known_first_frames_saved':'已保存首帧','canonical_query_no_snapshot':'规范URL查询成功，未返回快照（非全局无存档）','rate_limited_pending_verification':'HTTP429，存档情况未核验','not_queried':'尚未查询'}
    lines=[
        '# 分P首帧来源调查\n',
        f'核对日期：{data["checked_on"]}。范围为39个已归档正片投稿和1个预告，共40条目；不包含用户确认未在B站上线的8集。\n',
        '## 原始第一集快照到底包含什么\n',
        f'[第一集快照]({audit["source_snapshot"]})的合集目录位于 `{audit["collection_json_path"]}`，有{audit["collection_entries"]}个条目、{audit["collection_unique_cids"]}个唯一分P CID。合集各pages仅含以下字段：',
        '\n`'+', '.join(audit['collection_pages_field_names'])+'`\n',
        f'完整 `first_frame` 字段只在当前打开剧集的 `{audit["current_episode_json_path"]}`，共{len(audit["first_frame_fields"])}项，均属于S01E01。递归已保存初始状态及原HTML未发现其他集的隐藏首帧、预览拼图或视频流URL。**全合集CID目录不等于全合集首帧目录。**\n',
        '本次实际重新请求该快照遇到HTTP429；上述结构结论来自此前成功保存的原始页面及重新解析，不能声称本次已重新下载成功。已保存解码HTML的SHA256及字段路径见结构化清单。\n',
        '## 当前覆盖\n',
        f'- 已保存独立首帧：{summary["episodes_with_first_frames"]}集，共{count}张（S01E01、S01E03各6P）。',
        f'- 规范视频URL成功查询但未返回快照：{summary["status_counts"].get("canonical_query_no_snapshot",0)}条目。只针对所查URL，不证明所有URL变体或其他来源都没有存档。',
        f'- 本次补查遇HTTP429、待核验：{summary["status_counts"].get("rate_limited_pending_verification",0)}条目，包含预告。没有把这些响应算作“无存档”。',
        f'- 本次新增图片：{summary["new_images_this_check"]}张。请求已停止，不通过短间隔重复请求、代理或换域继续拉取。\n',
        '## 逐条记录\n',
        '|剧集/条目|BV|目录内分P数|已保存首帧数|查询/证据状态|\n|---|---|---:|---:|---|',
    ]
    for row in rows:
        lines.append(f'|{row["episode"]}|{row["bvid"]}|{row["catalogue_part_count"]}|{row["first_frame_count"]}|{labels[row["status"]]}|')
    lines += ['\n## 是否能继续用首帧对照原片\n',
        '可以，已取得各P首帧的集数优先采用这个方法：按CID核对图片来源，在相同版本原片中寻找对应帧，记录真实PTS、相似度、候选区间及首P例外，再更新该集映射和ASS。第三集就是从其独立页面快照取得首帧后完成的候选对齐。',
        '\n但不能从第一集这一页直接取出全集首帧；还需要其他集的独立页面存档或其他可靠画面依据。目前未取得完整全集首帧，HTTP429对应的条目尚不能判断是否有存档。',
        '\n首帧在原P内的采样偏移与原P精确时长仍可能未知。静态黑场需记录非唯一范围；若原P内部有删减或变速，还需要中间/尾部锚点。用户实播确认与技术测量的范围分别记录。',
        '\n## 数据与验证\n',
        '- `processing/first-frame-sources.json`：逐条BV、所查URL、状态、已取得图片与校验值、原快照结构审计。',
        '- 图片保留在既有 `calibration/S01E01/evidence/`、`calibration/S01E03/evidence/`，不另复制多套。',
        '- 执行 `python3 scripts/audit_first_frame_sources.py` 离线验证覆盖、CID及SHA256，并重建本文。无网络请求、不访问原视频。\n',
    ]
    (ROOT/'docs/首帧来源调查.md').write_text('\n'.join(lines).rstrip()+'\n')
    print(f'Validated {len(rows)} catalogue entries and {count} saved public images; HTTP429 remains unverified availability.')

if __name__=='__main__':main()
