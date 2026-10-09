"""Deterministically create teaching excerpts and original studies, no downloads."""
import json, re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
SCALES = [0,2,4,5,7,9,11]
traditional = [
("小星星 · 教学短编", 96, "1155665:2 4433221:2 5544332:2 5544332:2 1155665:2 4433221:2"),
("欢乐颂 · 主题片段", 100, "33455432112332:1.5 2:0.5 3:2 33455432112321:1.5 1:0.5 1:2"),
("两只老虎 · 轮唱主题", 108, "1231 1231 345:2 345:2 565431 565431 151:2 151:2"),
("玛丽有只小羊 · 教学短编", 100, "3212333:2 222:2 355:2 3212333322321:2"),
("伦敦桥 · 教学短编", 110, "5654345:2 234:2 345:2 5654345:2 2531:2"),
("划船歌 · 教学短编", 90, "11123:2 32345:2 1'1'1'555333111 54321:2"),
("铃儿响叮当 · 副歌片段", 116, "333:2 333:2 351:1.5 2:0.5 3:4 444:1.5 4:0.5 433335523:2 5:2"),
("哦苏珊娜 · 主题片段", 104, "1235531:1.5 2:0.5 3:2 3212212:2 1235531:1.5 2:0.5 3:2 3212211:2"),
("扬基歌 · 教学短编", 108, "1121315,:2 11211:1.5 7,:0.5 5,:2 11234543 217,5,6,7,1:2"),
("摇篮曲 · 勃拉姆斯主题片段", 76, "33:1.5 5:0.5 3:2 33:1.5 5:0.5 3:2 35:1.5 1':0.5 7:2 6:1.5 6:0.5 5:2 24:1.5 6:0.5 5:2 4:1.5 3:0.5 2:2 1:4")
]
original = [
("晨风小径", 88, "1356:2 5312:2 3465:2 321:3 1351':2 7653:2 4252:2 1:4"),
("月下灯火", 72, "6,136:2 5313:2 2465:2 32:2 6,136:2 7,246:2 5327,:2 1:4"),
("海边来信", 98, "1351':2 7653:2 2345:2 321:3 1461':2 7654:2 2532:2 1:4"),
("雨后回声", 84, "3532:2 1463:2 2521:2 7,6,:2 1356:2 4312:2 3652:2 1:4"),
("轻舟", 100, "1253:2 2465:2 3561':2 765:3 5312:2 4327,:2 1352:2 1:4"),
("星河晚安", 70, "6,13:2 532:2 7,24:2 653:2 135:2 61'7:2 6532 1:4"),
("纸鸢", 112, "13535 24646 35757 61'765 53125 4327,2 13521:4"),
("温柔的序章", 82, "13:2 24:2 35:2 46:2 57:2 61':2 7653 24321:4")
]
exercises = [
("C 大调 · 上行音阶", 90, "12345671':2 1'2345671':2", False),
("C 大调 · 下行音阶", 90, "1'7654321:2 1'7654321:2", False),
("三八度 · 键位熟悉", 84, "1,2,3,4,5,6,7,12345671'2'3'4'5'6'7':3", False),
("三度音程 · 稳定节奏", 96, "132435465761'72' 2'71'6756453423121:3", False),
("五声音阶 · 轻快练习", 110, "123561'65321:2 13561'65321:3", False),
("四分与八分 · 节奏练习", 96, "1 2:0.5 3:0.5 4 5:2 5 4:0.5 3:0.5 2 1:2", False),
("休止符 · 停顿练习", 96, "1 0 3 0 5:2 0 6 0 5 0 3:2 0 2 0 1:3", False),
("C 和弦 · 同步练习", 84, "(135):2 (146):2 (257):2 (135):4 (351'):2 (461'):2 (572'):2 (351'):4", False),
("分解和弦 · C / F / G", 96, "135351' 146461' 257572' 13531:3", False),
("旋律与低音 · 双轨练习", 90, "1356:2 5312:2 3465:2 321:3 1351':2 7653:2 4252:2 1:4", True),
("重复键 · 速度练习", 100, "1111 2222 3333 5555 6666 5555 3333 1111:2", False),
("和弦转位 · 声部练习", 88, "(135):2 (351'):2 (51'3'):2 (461'):2 (61'4'):2 (572'):2 (72'5'):2 (351'):4", False)
]

def parse(body, bpm):
    notes, at = [], 0.0
    for token in body.split():
        if ':' in token: token, duration = token.rsplit(':',1); beats=float(duration)
        else: beats=1.0
        chord = token.startswith('(')
        content = token[1:-1] if chord else token
        atoms = re.findall(r"[1-7][',]*|0", content)
        assert ''.join(atoms)==content, token
        for index, atom in enumerate(atoms):
            atom_beats = beats if chord or index == len(atoms)-1 else 1.0
            if atom != '0':
                pitch=60+SCALES[int(atom[0])-1]+12*(atom.count("'")-atom.count(','))
                notes.append(dict(pitch=pitch,startMs=round(at,3),durationMs=round(atom_beats*60000/bpm,3),track=0,velocity=88,percussion=False))
            if not chord: at += atom_beats*60000/bpm
        if chord: at += beats*60000/bpm
    return notes

def main():
    out=ROOT/'Songs'; out.mkdir(exist_ok=True)
    manifest=[]
    items = [(t,b,n,'传统旋律','本项目手工编写的传统/古典旋律教学短编；非第三方 MIDI 转载。',False) for t,b,n in traditional]
    items += [(t,b,n,'原创短曲','本项目原创演示旋律，不对应商业歌曲。',False) for t,b,n in original]
    items += [(t,b,n,'演奏练习','本项目原创音阶、节奏、和弦教学练习。',bass) for t,b,n,bass in exercises]
    for i,(title,bpm,body,category,description,bass) in enumerate(items,1):
        notes=parse(body,bpm)
        if bass:
            duration=max(n['startMs']+n['durationMs'] for n in notes)
            for j in range(int(duration/(60000/bpm*4))):
                notes.append(dict(pitch=[48,53,55,48][j%4],startMs=round(j*60000/bpm*4,3),durationMs=round(60000/bpm*3,3),track=1,velocity=64,percussion=False))
        song=dict(version=1,title=title,author='琴伴 · 演示编配',category=category,source='琴伴内置教学谱 · 新增编配 CC0-1.0',description=description+' 本谱可能仅为主题片段，不是完整原曲。',bpm=bpm,notes=sorted(notes,key=lambda n:(n['startMs'],n['pitch'])))
        name=f'{i:02d}.json'
        (out/name).write_text(json.dumps(song,ensure_ascii=False,indent=2),encoding='utf-8')
        manifest.append(dict(file=name,title=title,category=category,notes=len(notes)))
    (ROOT/'tools'/'builtin-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'Generated {len(items)} individual teaching scores; no external assets downloaded')
if __name__=='__main__': main()
