"""Offline validation and evidence-only timeline report; Python 3.9+ stdlib."""
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / 'hacks-danmaku'
NOT_UPLOADED = ['S03E07', 'S03E08', 'S03E09', 'S04E05', 'S04E06', 'S04E08', 'S04E09', 'S04E10']

def require(condition, message):
    if not condition:
        raise ValueError(message)

def fields(data):
    pos = 0
    def varint():
        nonlocal pos
        number = shift = 0
        while pos < len(data) and shift < 70:
            value = data[pos]
            pos += 1
            number |= (value & 127) << shift
            if value < 128:
                return number
            shift += 7
        raise ValueError('Invalid/truncated protobuf varint')
    while pos < len(data):
        tag = varint()
        kind, key = tag & 7, tag >> 3
        require(key > 0, 'Protobuf field zero')
        if kind == 0:
            value = varint()
        elif kind in (1, 2, 5):
            size = varint() if kind == 2 else (8 if kind == 1 else 4)
            require(pos + size <= len(data), 'Truncated protobuf bytes')
            value = data[pos:pos + size]
            pos += size
        else:
            raise ValueError(f'Unsupported protobuf wire type: {kind}')
        yield key, value

def decode(data):
    # Legitimate protobuf may start with b'\n{'; do not use lstrip prefix tests.
    try:
        obj = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError):
        obj = None
    require(not isinstance(obj, dict), 'Expected protobuf, found JSON response')
    rows = []
    for key, value in fields(data):
        if key == 1 and isinstance(value, bytes):
            row = dict(fields(value))
            require(isinstance(row.get(7), bytes), 'Missing danmaku text')
            rows.append(row)
    return rows

def load(name):
    return json.loads((ARCHIVE / name).read_text(encoding='utf-8'))

def duration(seconds):
    if seconds is None:
        return '待测'
    return f'{seconds//3600:02d}:{seconds%3600//60:02d}:{seconds%60:02d}'

def main():
    episodes = load('CID目录.json')
    downloads = load('分段下载结果.json')
    by_cid = {row['cid']:row for row in downloads}
    require(len(by_cid) == len(downloads), 'Duplicate CID in download manifest')
    verified_parts = verified_segments = comments = named_comments = 0
    used = set()
    report = []
    for episode in episodes:
        match = re.search(r'S\d+E\d+', episode['title'])
        label = match.group() if match else 'S05_预告'
        status = {
            'episode':label,
            'bvid':episode['bvid'],
            'source_title':episode['title'],
            'source_duration_precision':'integer_seconds_from_archived_metadata',
            'nas_media_duration_seconds':None,
            'nas_alignment_status':'not_measured',
            'overlap_evidence':'user_reports_overlapping_adjacent_parts_exact_amount_unknown',
            'cut_status':'unverified',
            'named_parts_duration_sum_seconds':0,
            'named_part_count':0,
            'raw_comment_count':0,
            'parts':[],
        }
        for page in episode['pages']:
            cid = page['cid']
            require(cid in by_cid, f'CID missing: {cid}')
            require(cid not in used, f'Duplicate source CID: {cid}')
            used.add(cid)
            result = by_cid[cid]
            require('error' not in result and result.get('file'), f'Failed download: {cid}')
            xml = (ARCHIVE / result['file']).resolve()
            require(ARCHIVE in xml.parents and xml.exists(), f'Invalid manifest path: {xml}')
            elements = ET.parse(xml).getroot().findall('d')
            require(len(elements) == result['count'], f'XML count mismatch: {xml}')
            original = {}
            for index in range(1, max(1, math.ceil(page['duration'] / 360)) + 1):
                pb = xml.with_suffix(f'.segment{index:02d}.pb')
                for row in decode(pb.read_bytes()):
                    dmid = row.get(12, b'').decode() or str(row.get(1, 0))
                    original[dmid] = row
                verified_segments += 1
            ids = []
            times = []
            for item in elements:
                props = item.attrib['p'].split(',')
                require(len(props) >= 8, f'Invalid XML p: {xml}')
                dmid = props[7]
                ids.append(dmid)
                require(dmid in original, f'XML ID missing from protobuf: {xml}, {dmid}')
                row = original[dmid]
                require((item.text or '') == row[7].decode('utf-8', errors='replace'), f'Text mismatch: {xml}, {dmid}')
                require(abs(float(props[0]) - row.get(2, 0) / 1000) < 0.00001, f'Time mismatch: {xml}, {dmid}')
                times.append(float(props[0]))
            require(len(ids) == len(set(ids)) and set(ids) == set(original), f'ID/count mismatch: {xml}')
            is_named = bool(match and re.match(re.escape(label) + r'-\d+', page['part']))
            if is_named:
                status['named_parts_duration_sum_seconds'] += page['duration']
                status['named_part_count'] += 1
                named_comments += len(elements)
            page_status = {
                'page':page['page'], 'part':page['part'], 'cid':cid,
                'archived_duration_seconds':page['duration'], 'comment_count':len(elements),
                'comment_min_seconds':min(times) if times else None,
                'comment_max_seconds':max(times) if times else None,
                'temporary_merge_role':'included_named_slice' if is_named else 'excluded_nonstandard_part',
                'numeric_placeholder':page['part'] in ('0', '1'),
                'cut_label_unverified':'删' in page['part'],
                'original_media_start_seconds':None, 'original_media_end_seconds':None,
                'overlap_with_previous_seconds':None,
            }
            if page_status['cut_label_unverified']:
                status['cut_status'] = 'suspected_from_part_name_not_measured'
            status['parts'].append(page_status)
            verified_parts += 1
            comments += len(elements)
            status['raw_comment_count'] += len(elements)
        if not status['named_part_count']:
            status['named_parts_duration_sum_seconds'] = None
        report.append(status)
    require(used == set(by_cid), 'Download manifest has extra CIDs')
    require((verified_parts, verified_segments, comments) == (291, 369, 29782), 'Baseline totals changed; inspect before updating expectations')
    payload = {
        'source_snapshot_utc':'2026-09-09T14:40:54Z',
        'capture_date_asia_shanghai':'2026-10-28',
        'verification':{'parts':verified_parts,'protobuf_segments':verified_segments,'comments':comments,'named_slice_comments':named_comments},
        'not_uploaded_to_bilibili':{'confirmed_by':'repository owner in conversation on 2026-10-28','episodes':NOT_UPLOADED,'expected_danmaku':'none','retry_required':False},
        'episodes':report,
    }
    processing = ROOT / 'processing'
    docs = ROOT / 'docs'
    processing.mkdir(exist_ok=True)
    docs.mkdir(exist_ok=True)
    (processing/'timeline-status.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines = [
        '# 时间轴状态（尚未实测校准）\n',
        '本表由 `python3 scripts/audit_archive.py` 根据归档数据生成。时长来自存档页面的整数秒元数据，不是 NAS 原片精确时长。相邻重叠量、NAS 原片时长和删减区间尚无实测值，均不填猜测数字。\n',
        '相邻 P 的重叠由用户确认存在，但不能用整集时长差均摊每处重叠。`【删】` 是名称线索，不能直接确定真实删减位置。\n',
        '|剧集|命名切片数|命名切片时长总和（未扣重叠）|原始弹幕数|疑似删减|未参与合并的原页码|NAS 时长|\n|---|---:|---|---:|---|---|---|',
    ]
    for row in report:
        excluded = [str(p['page']) for p in row['parts'] if p['temporary_merge_role']=='excluded_nonstandard_part']
        cut = '名称含【删】，未实测' if row['cut_status']!='unverified' else '待核对'
        lines.append(f'|{row["episode"]}|{row["named_part_count"]}|{duration(row["named_parts_duration_sum_seconds"])}|{row["raw_comment_count"]}|{cut}|{", ".join(excluded) or "无"}|待测|')
    lines += ['\n## 名称标记的疑似删减\n', '|剧集|原页码|分 P|CID|存档时长|\n|---|---:|---|---:|---|']
    for row in report:
        for page in row['parts']:
            if page['cut_label_unverified']:
                lines.append(f'|{row["episode"]}|{page["page"]}|{page["part"]}|{page["cid"]}|{duration(page["archived_duration_seconds"])}|')
    lines += ['\n## 独立保留的占位或非标准分 P\n',
              '下表条目不串入命名切片时间轴；保留原始弹幕。名称为0/1与少量弹幕都不能单独证明视频身份。S05E08/E09还可能存在视频替换或填充，不能按当前长时长缩放弹幕；必须结合原片核对。\n',
              '|剧集|原页码|分 P|存档视频时长（秒）|弹幕数|最早/最晚弹幕秒数|\n|---|---:|---|---:|---:|---|']
    for row in report:
        for page in row['parts']:
            if page['temporary_merge_role']=='excluded_nonstandard_part':
                times = f'{page["comment_min_seconds"]} / {page["comment_max_seconds"]}' if page['comment_count'] else '无弹幕'
                lines.append(f'|{row["episode"]}|{page["page"]}|{page["part"]}|{page["archived_duration_seconds"]}|{page["comment_count"]}|{times}|')
    lines += ['\n## 预期无弹幕的8集\n', ', '.join(NOT_UPLOADED)+'。用户确认未在 B 站上线，不再列为补抓任务。\n',
              '## 待获取的校准依据\n',
              '1. 这台 Mac 可读取的 NAS 五季原视频路径及逐集精确媒体时长。',
              '2. 各 B 站分 P 可与原片比对的音频、视频或字幕锚点；现有弹幕文件没有音视频内容。',
              '3. 每个 P 在原片中的区间或多段映射，以及重叠和删减的实测证据。\n',
              '现有37份 merged XML仅累加命名切片时长；占位P已排除，相邻重叠仍未校准。原始分P时间保留不变。\n']
    (docs/'时间轴状态.md').write_text('\n'.join(lines).rstrip()+'\n',encoding='utf-8')
    print(f'Validated {verified_parts} parts / {verified_segments} protobuf segments / {comments} comments; generated timeline status (not calibrated).')

if __name__ == '__main__':
    main()
