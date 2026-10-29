"""Offline verification and report for public first-frame evidence coverage."""
from collections import Counter
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def verify_internet_search(catalog):
    search=json.loads((ROOT/'processing/first-frame-internet-search.json').read_text())
    refs=json.loads((ROOT/search['new_upload_manifest']).read_text())
    original_cids={p['cid']for e in catalog for p in e['pages']}
    posts={p['bvid']:p for p in refs['posts']}
    seen=set()
    for row in refs['images']:
        key=(row['bvid'],row['cid'])
        if key in seen or row['cid']in original_cids:
            raise ValueError('New-upload evidence must have distinct new CIDs')
        seen.add(key)
        post=posts[row['bvid']]
        page=next(p for p in post['pages']if p['cid']==row['cid'])
        if row['page']!=page['page']or row['part']!=page['part']or row['duration_seconds']!=page['duration']:
            raise ValueError('New-upload image metadata mismatch')
        if row['first_frame_url']!=page['first_frame'].replace('http://','https://'):
            raise ValueError('Image URL does not match public page evidence')
        if post['owner']['mid']!=436788072 or row['old_cid_mapping_status']!='unverified_new_upload_only':
            raise ValueError('Update source scope or unverified new-upload status')
        path=(ROOT/row['file']).resolve()
        if ROOT not in path.parents or row['http_status']!=200:
            raise ValueError('Invalid downloaded reference')
        body=path.read_bytes()
        if not body.startswith(b'\xff\xd8')or hashlib.sha256(body).hexdigest()!=row['sha256']or len(body)!=row['bytes']:
            raise ValueError('New-upload JPEG checksum or size mismatch')
        expected='placeholder'if row['part']in['0','1']else'episode_segment'
        if row['part_kind']!=expected:
            raise ValueError('Placeholder classification mismatch')
    named=sum(r['part_kind']=='episode_segment'for r in refs['images'])
    summary=refs['summary']
    if summary!={'new_uploads':len(posts),'saved_images':len(seen),'episode_segment_images':named,'placeholder_images':len(seen)-named,'old_cid_images_recovered':0}:
        raise ValueError('New-upload evidence totals mismatch')
    if search['summary']['new_upload_reference_images']!=len(seen)or search['summary']['new_old_cid_first_frames']!=0:
        raise ValueError('Expanded search must distinguish original and new images')
    candidates=json.loads((ROOT/search['new_old_correspondence_candidates']).read_text())
    old_pages={p['cid']:p for e in catalog for p in e['pages']}
    new_pages={p['cid']:p for post in posts.values()for p in post['pages']}
    for pair in candidates['pairs']:
        old=old_pages[pair['old_cid']];new=new_pages[pair['new_cid']]
        if pair['old_part']!=old['part']or pair['new_part']!=new['part']or pair['old_duration_seconds']!=old['duration']or pair['new_duration_seconds']!=new['duration']:
            raise ValueError('Candidate correspondence metadata mismatch')
        if not pair['verification_status'].startswith('unverified:'):
            raise ValueError('Candidate correspondence is not visually verified')
    for episode in ['S03E05','S04E01']:
        cached=json.loads((ROOT/f'references/cache-metadata/biliplus-view-{episode.lower()}.json').read_text())
        original=next(e for e in catalog if e['bvid']==cached['v2_app_api']['bvid'])
        if [(p['cid'],p['part'])for p in cached['list']]!=[(p['cid'],p['part'])for p in original['pages']]:
            raise ValueError('Cached CIDs differ from original catalogue')
    for request in search['third_party_queries']:
        if request.get('saved_response_file'):
            body=(ROOT/request['saved_response_file']).read_bytes()
            if hashlib.sha256(body).hexdigest()!=request['sha256']or len(body)!=request['bytes']:
                raise ValueError('Public cache response checksum mismatch')
    if refs.get('visual_match_candidates'):
        visual=json.loads((ROOT/refs['visual_match_candidates']).read_text())
        by_cid={r['cid']:r for r in refs['images']}
        matches=0;intros=0
        for post in visual['posts']:
            if Path(post['reference']['release']).name!=post['reference']['release']:
                raise ValueError('Reference release must not contain a personal path')
            for anchor in post['anchors']:
                image=by_cid[anchor['new_cid']]
                if anchor.get('candidate_pts')is None:
                    intros+=1
                    continue
                matches+=1
                if anchor['reference_image_sha256']!=image['sha256']or anchor['reference_image_file']!=image['file']:
                    raise ValueError('Visual candidate source image mismatch')
                if anchor['combined_score']<.95 or anchor['best_at_window_edge']:
                    raise ValueError('Visual candidate needs further quality review')
                if not 0<=anchor['candidate_time_seconds']<post['reference']['duration_seconds']:
                    raise ValueError('Visual candidate lies outside reference duration')
                if abs(anchor['candidate_time_seconds']-anchor['candidate_pts']/24000)>1e-8:
                    raise ValueError('Visual candidate PTS/time mismatch')
                if anchor['old_cid_correspondence']!='unverified':
                    raise ValueError('New-upload visual evidence cannot verify old-CID correspondence')
        if visual['summary']!={'matched_non_intro_images':matches,'intro_images_without_unique_start':intros,'old_cid_mappings_verified':0,'old_danmaku_mapping_changed_using_new_images':False}:
            raise ValueError('Visual candidate totals mismatch')
    return search,refs

def main():
    data=json.loads((ROOT/'processing/first-frame-sources.json').read_text())
    catalog=json.loads((ROOT/'hacks-danmaku/CID目录.json').read_text())
    search,refs=verify_internet_search(catalog)
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
        ('本次冷却后成功重新取得原始快照；递归核对的字段范围与此前保存版本一致。已保存解码HTML的SHA256及字段路径见结构化清单。\n'
         if audit.get('latest_fetch',{}).get('http_status')==200 and audit['latest_fetch'].get('parsed_initial_state_verified') else
         '本次实际重新请求该快照遇到HTTP429或其他访问错误；上述结构结论来自此前成功保存的原始页面及重新解析，不能声称本次已重新下载成功。已保存解码HTML的SHA256及字段路径见结构化清单。\n'),
        '## 当前覆盖\n',
        f'- 旧CID已保存独立首帧：{summary["episodes_with_first_frames"]}集，共{count}张（'+ '、'.join(r['episode']for r in rows if r['first_frame_count'])+'）。',
        f'- 规范视频URL成功查询但未返回快照：{summary["status_counts"].get("canonical_query_no_snapshot",0)}条目。只针对所查URL，不证明所有URL变体或其他来源都没有存档。',
        f'- 规范URL调查最后仍因HTTP429而待核验：{summary["status_counts"].get("rate_limited_pending_verification",0)}条目。变体查询的新限流另列于下文。',
        f'- 规范URL调查新增旧CID图片：{summary["new_images_this_check"]}张。初轮遇到限流后停止；冷却后仅以单线程、每HTTP调用至少8秒的间隔复核，遇429即停，不使用代理或换域规避。',
        f'- 扩展互联网搜索另存{refs["summary"]["saved_images"]}张**新投稿、新CID**参考图，其中正片命名P {refs["summary"]["episode_segment_images"]}张、数字名占位P {refs["summary"]["placeholder_images"]}张；没有计入上面的旧CID覆盖。\n',
        '## 逐条记录\n',
        '|剧集/条目|BV|目录内分P数|已保存首帧数|查询/证据状态|\n|---|---|---:|---:|---|',
    ]
    for row in rows:
        lines.append(f'|{row["episode"]}|{row["bvid"]}|{row["catalogue_part_count"]}|{row["first_frame_count"]}|{labels[row["status"]]}|')
    lines += ['\n## 扩展互联网搜索：找到两个现存新投稿\n',
        '从UP主当前公开合集找到以下两条投稿。普通网页的公开SSR数据包含逐P的 `cid` 与 `first_frame`，28张图片均成功保存并核对SHA256。此处没有将网页HTTP200或API code0本身当作图片成功。\n',
        '|新投稿|UP主说明|全部P首帧|正片命名P首帧|页面弹幕计数（未下载）|\n|---|---|---:|---:|---:|',
    ]
    for post in refs['posts']:
        images=[r for r in refs['images']if r['bvid']==post['bvid']]
        lines.append(f'|[{post["bvid"]}]({post["source_page"]})|{post["episode_claimed_in_description"]}|{len(images)}|{sum(r["part_kind"]=="episode_segment"for r in images)}|{post["stat_at_check"]["danmaku"]}|')
    lines += [
        '\n这些是新投稿的首帧，**不是旧CID首帧的恢复**。S04E01前8个正片P的序号和181秒显示时长相同，已保存新旧CID对应候选；但旧尾段181+202秒，新尾段为121+121+144秒，存在重切，不能逐P机械替换，也不能据此宣布旧弹幕已精确校准。',
        '\nS04E09属于原40条目目录之外的新发现，原归档中的缺失记录与29,782条总数不变；本轮保存参考图和公开元数据，未抓取新投稿弹幕。新画面的后续匹配另列于下文，原片和原片截图不入库。\n',
        '后续已对照完整原片：22张非片头首帧均找到高相似画面候选（综合分数至少0.9749），两个正片首P的重复片头标志没有强行指定唯一起点。4个初轮低分候选经扩大窗口检索后找到高相似帧，保留搜索提示、原候选与最终PTS；时长提示仅选择搜索窗口，最终依据是图像匹配。新旧CID对应仍未验证，旧弹幕没有据此改轴。结果见 `references/reuploads/visual-match-candidates.json`。\n',
        '### 其他已实际核查的路线\n',
        '|路线|本轮范围与结果|\n|---|---|',
        '|BiliPlus|批量查询40个aid，命中S01E01/S03E05/S04E01的标题/封面缓存；后两集完整缓存、view_all、CID历史没有首帧。缓存CID与原目录一致；S01E02实际缓存接口返回-404。|',
        '|唧唧及备用站|S01E02实际get_info为删除占位，get_download_info为空；备用站跳首页、HTTP502或TLS错误，不算有图片，也不据此断定互联网无资源。|',
        '|Wayback变体|E02的AV地址首请求HTTP429即停止，其余13个计划AV/mobile/API查询未执行；这些URL保持未知。|',
        '|Ghostarchive|E02两个完整BV/AV地址明确无存档；6个BV/aid子串查询HTTP200但空体，保持未知。|',
        '|Arquivo.pt|E02 BV/AV、E04 BV、E05 BV共4个确切地址HTTP200且没有历史记录；不扩大解释到其他URL。|',
        '|Common Crawl|2026-43与2026-39索引的5个有界BV前缀查询连续HTTP504后停止；没有取得可判断存在与否的索引结果。|',
        '|搜索引擎与动态|精确BV/aid及标题查询未取得与旧CID相连的首帧URL；公开动态一次HTTP412后停止。普通搜索正文和剧情图不充当分P首帧。|',
        '\n逐请求URL、HTTP/业务结果、响应SHA256与未查范围见 `processing/first-frame-internet-search.json`。首帧随机文件名仍需完整元数据URL，本轮未找到从CID确定推导文件名的公开依据，没有盲扫CDN。',
        '\n## 是否能继续用首帧对照原片\n',
        '可以，已取得各P首帧的集数优先采用这个方法：按CID核对图片来源，在相同版本原片中寻找对应帧，记录真实PTS、相似度、候选区间及首P例外，再更新该集映射和ASS。第三集就是从其独立页面快照取得首帧后完成的候选对齐。',
        '\n但不能从第一集这一页直接取出全集首帧；还需要其他集的独立页面存档或其他可靠画面依据。目前未取得完整全集首帧。规范URL空结果只针对本次查询范围；如仍有HTTP429条目，其存档可用性继续保留为未知。',
        '\n首帧在原P内的采样偏移与原P精确时长仍可能未知。静态黑场需记录非唯一范围；若原P内部有删减或变速，还需要中间/尾部锚点。用户实播确认与技术测量的范围分别记录。',
        '\n## 数据与验证\n',
        '- `processing/first-frame-sources.json`：逐条BV、所查URL、状态、已取得图片与校验值、原快照结构审计。',
        '- `processing/first-frame-internet-search.json`：规范URL以外的扩展搜索、成功与失败范围，区分未知和明确空结果。',
        '- `references/reuploads/`：新投稿公开页面字段提取、28张首帧、SHA256及未验证的新旧对应候选；不覆盖原CID证据。',
        '- `references/cache-metadata/`：BiliPlus公开缓存响应，保存命中内容但不把普通封面记为首帧。',
        '- 图片保留在既有 `calibration/S01E01/evidence/`、`calibration/S01E03/evidence/`，不另复制多套。',
        '- 执行 `python3 scripts/audit_first_frame_sources.py` 离线验证覆盖、CID及SHA256，并重建本文。无网络请求、不访问原视频。\n',
    ]
    (ROOT/'docs/首帧来源调查.md').write_text('\n'.join(lines).rstrip()+'\n')
    from build_playback_checklist import write_outputs
    write_outputs()
    print(f'Validated {len(rows)} catalogue entries, {count} original-CID images and {len(refs["images"])} separate new-upload images; unverified correspondences remain candidates.')

if __name__=='__main__':main()
