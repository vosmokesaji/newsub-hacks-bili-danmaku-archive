"""Rebuild an archived timing map without publishing or modifying source media."""
import argparse
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
COMMENT = 'LOCAL CANDIDATE PREVIEW: assumes each first_frame has zero in-part sampling offset; P1 starts at reference zero. Not a verified piecewise timeline.'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inside(relative):
    path = (ROOT/relative).resolve()
    if ROOT not in path.parents:
        raise ValueError('Artifact paths must stay inside the archive repository')
    return path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('episode')
    ap.add_argument('--check',action='store_true',help='validate provenance and artifacts without writing')
    args=ap.parse_args()
    folder=inside('calibration/'+args.episode)
    manifest_path=folder/'alignment.json'
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('mapping') is None:
        if not args.check:
            raise ValueError('No independently supported mapping is archived for this episode')
        count=0
        for source in manifest['original_parts']:
            path=inside(source['file'])
            if digest(path)!=source['sha256']:
                raise ValueError('Original data checksum mismatch')
            rows=ET.parse(path).getroot().findall('d')
            if len(rows)!=source['comments']:
                raise ValueError('Original count mismatch')
            count+=len(rows)
        for info in manifest['artifacts'].values():
            if digest(inside(info['file']))!=info['sha256']:
                raise ValueError('Uncalibrated artifact checksum mismatch')
        if 'ass'in manifest['artifacts'] or 'aligned_xml'in manifest['artifacts']:
            raise ValueError('Pending mapping must not claim aligned playback artifacts')
        print(f'{args.episode}: {count} original comments and naive merge verified; alignment remains pending')
        return
    offsets={p['cid']:p['preview_offset_seconds']for p in manifest['mapping']}
    tree=ET.Element('i')
    ET.SubElement(tree,'source').text=manifest['bvid']
    tree.append(ET.Comment(manifest.get('xml_comment',COMMENT)))
    seen=set()
    for source in manifest['original_parts']:
        path=inside(source['file'])
        if digest(path)!=source['sha256']:
            raise ValueError('Original data checksum mismatch: '+source['file'])
        rows=ET.parse(path).getroot().findall('d')
        if len(rows)!=source['comments']:
            raise ValueError('Original comment count mismatch')
        for row in rows:
            fields=row.attrib['p'].split(',')
            if fields[7]in seen:
                raise ValueError('Unexpected cross-part duplicate ID')
            seen.add(fields[7])
            fields[0]=f'{float(fields[0])+offsets[source["cid"]]:.6f}'.rstrip('0').rstrip('.')
            row.attrib['p']=','.join(fields)
            tree.append(row)
    xml_path=folder/'aligned.xml'
    generated=ET.tostring(tree,encoding='utf-8',xml_declaration=True)
    if args.check:
        if generated!=xml_path.read_bytes():
            raise ValueError('XML is not reproducible from archived mapping')
        for info in manifest['artifacts'].values():
            if digest(inside(info['file']))!=info['sha256']:
                raise ValueError('Generated artifact checksum mismatch: '+info['file'])
        for image in manifest.get('reference_images',[]):
            if digest(inside(image['file']))!=image['sha256']:
                raise ValueError('Public source image checksum mismatch')
        ass_path=inside(manifest['artifacts']['ass']['file'])
        lines=ass_path.read_text(encoding='utf-8-sig').splitlines()
        if sum(line.startswith('Dialogue:')for line in lines)!=len(seen):
            raise ValueError('ASS event count mismatch')
        print(f'{args.episode}: originals, reproducible XML, {len(seen)} comments, ASS and source images verified')
        return
    from biliass import convert_to_ass
    xml_path.write_bytes(generated)
    style=manifest['ass_style']
    ass=convert_to_ass(generated,1920,1080,input_format='xml',
        display_region_ratio=style['display_region_ratio'],font_face=style['font_face'],
        font_size=style['font_size'],text_opacity=style['opacity'],
        duration_marquee=style['marquee_seconds'],duration_still=style['still_seconds'],reduce_comments=False)
    name=Path(manifest['reference']['release']).with_suffix('.ass').name
    ass_path=folder/name
    ass_path.write_text(ass,encoding='utf-8-sig')
    if sum(line.startswith('Dialogue:')for line in ass.splitlines())!=len(seen):
        raise ValueError('Conversion dropped comments')
    for role,path in [('aligned_xml',xml_path),('ass',ass_path)]:
        manifest['artifacts'][role]={'file':str(path.relative_to(ROOT)),'sha256':digest(path)}
    manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(f'{args.episode}: rebuilt {len(seen)} comments; original parts unchanged')

if __name__=='__main__':main()
