"""Deterministic local SMF fixtures: 20 rhythms x 5 tempo scenarios. NOT songs.
No download, transcription, input injection or changes to Songs/UserData.
"""
import argparse, hashlib, json, random, struct
from fractions import Fraction
from pathlib import Path
from smf_reference import parse_smf


def vlq(value):
    result = [value & 127]
    while value >> 7:
        value >>= 7
        result.insert(0, (value & 127) | 128)
    return bytes(result)


def chunk(events, end_tick, running=False):
    events = sorted(events, key=lambda e: (e[0], e[1], e[2]))
    data = bytearray(); at = 0; previous = None
    for tick, priority, event in events:
        data += vlq(tick-at)
        if running and event[0] < 0xf0 and event[0] == previous:
            data += event[1:]
        else:
            data += event
        previous = event[0] if event[0] < 0xf0 else None
        at = tick
    data += vlq(end_tick-at) + b'\xff\x2f\x00'
    return b'MTrk' + struct.pack('>I', len(data)) + data


def generate(index):
    rhythm = index % 20; scenario = index // 20
    rng = random.Random(4100 + index); ppq = [480, 960, 240, 480, 960][scenario]
    tempos = [(0, [500000, 400000, 750000, 600000, 333333][scenario])]
    if scenario >= 1: tempos += [(ppq*2, 500001), (ppq*5, 375000)]
    if scenario >= 3: tempos += [(ppq*9, 666667)]
    conductor = [(t, 0, b'\xff\x51\x03' + us.to_bytes(3,'big')) for t, us in tempos]
    notes = []; voice = [[], []]
    durations = [ppq//4, ppq//2, ppq, ppq*3//2, ppq*2, ppq//3, ppq*2//3, ppq*3, ppq//8]
    at = ppq//4 if rhythm % 2 else 0
    for group in range(12):
        duration = durations[(group+rhythm) % len(durations)]
        pitches = [48 + rng.randrange(25)]
        if group % 4 == rhythm % 4: pitches += [pitches[0]+4, pitches[0]+7]
        velocity = 40 + rng.randrange(80)
        for pitch in pitches:
            voice[0] += [(at,1,bytes([0x90,pitch,velocity])), (at+duration,0,bytes([0x80,pitch,0]))]
            notes.append((1,pitch,at,at+duration,velocity,False))
        # A separate sparse lower voice or MIDI percussion channel.
        if group % 3 == 0:
            start = at + ppq//8; length = duration + ppq//2
            channel = 9 if rhythm % 3 == 0 else 1; pitch = 36 + rng.randrange(12)
            voice[1] += [(start,1,bytes([0x90+channel,pitch,90])), (start+length,0,bytes([0x80+channel,pitch,0]))]
            notes.append((2,pitch,start,start+length,90,channel==9))
        at += duration + (ppq//2 if group % 3 == 1 else ppq//8)
    end_tick = max(at+ppq, max(t for t,_,_ in conductor)+ppq)
    data = b'MThd' + struct.pack('>IHHH',6,1,3,ppq) + chunk(conductor,end_tick) + chunk(voice[0],end_tick,rhythm%2==1) + chunk(voice[1],end_tick,rhythm%2==1)
    reference = parse_smf(data)
    # Independent exact rational integral of the authored tempo schedule (not the SMF parser).
    def metric(tick):
        total = Fraction(0)
        for i,(start,tempo) in enumerate(tempos):
            end = min(tick,tempos[i+1][0] if i+1<len(tempos) else tick)
            if end>start: total += Fraction((end-start)*tempo,ppq*1000)
        return float(total)
    expected = sorted((tr,p,metric(s),metric(e)-metric(s),v,perc) for tr,p,s,e,v,perc in notes)
    actual = sorted((n['track'],n['pitch'],n['startMs'],n['durationMs'],n['velocity'],n['percussion']) for n in reference['notes'])
    assert len(actual)==len(expected)
    for a,b in zip(actual,expected):
        assert a[0:2]==b[0:2] and a[4:]==b[4:]
        assert abs(a[2]-b[2])<1e-8 and abs(a[3]-b[3])<1e-8
    assert abs(reference['lengthMs']-metric(end_tick))<1e-8
    reference['synthetic'] = True; reference['notAGoldenSongSample'] = True
    return data, reference


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('new_output_directory',type=Path); args=parser.parse_args()
    root = args.new_output_directory.resolve()
    if root.exists(): raise SystemExit('Refusing to overwrite existing output or evidence.')
    root.mkdir(parents=True)
    results=[]
    for i in range(100):
        data, reference=generate(i); stem=f'timing-fixture-{i+1:03}'
        (root/(stem+'.mid')).write_bytes(data)
        (root/(stem+'.reference.json')).write_text(json.dumps(reference,ensure_ascii=False,indent=2),encoding='utf-8')
        results.append(dict(name=stem,sha256=hashlib.sha256(data).hexdigest(),notes=len(reference['notes']),tempoChanges=reference['tempoChanges'],durationKinds=reference['durationKinds']))
    (root/'fixture-manifest.json').write_text(json.dumps(dict(cases=100,actualSongsAdded=0,goldenSongs=0,dataset='self-authored TIMING TEST FIXTURES; not songs',independentReference='SMF parser compared to authored Fraction tempo integrals',results=results),indent=2),encoding='utf-8')
    print(f'PASS 100 local timing fixtures with independent rational reference; golden songs = 0; {root}')


if __name__=='__main__': main()
