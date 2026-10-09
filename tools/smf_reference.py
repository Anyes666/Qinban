"""Independent standard-MIDI reference. No audio inference or synthesized notes."""
import bisect,struct
from collections import defaultdict,deque

def parse_smf(data):
    if len(data)<14 or data[:4]!=b"MThd": raise ValueError("not a standard MIDI file")
    length=int.from_bytes(data[4:8],"big");fmt,count,division=struct.unpack(">HHH",data[8:14])
    if fmt not in (0,1) or count>256 or division==0 or division&0x8000:raise ValueError("unsupported timing format")
    pos=8+length;notes=[];tempos=[];last_tick=0
    def vlq(buf,at):
        value=0
        for _ in range(4):
            if at>=len(buf):raise ValueError("truncated variable-length value")
            c=buf[at];at+=1;value=(value<<7)|(c&127)
            if c<128:return value,at
        raise ValueError("invalid variable-length value")
    for track in range(count):
        if data[pos:pos+4]!=b"MTrk":raise ValueError("missing MIDI track")
        size=int.from_bytes(data[pos+4:pos+8],"big");buf=data[pos+8:pos+8+size];pos+=8+size
        if len(buf)!=size:raise ValueError("truncated track")
        at=0;tick=0;running=None;pending=defaultdict(deque)
        while at<len(buf):
            delta,at=vlq(buf,at);tick+=delta;last_tick=max(last_tick,tick)
            if at>=len(buf):raise ValueError("missing event")
            status=buf[at]
            if status>=128:at+=1
            elif running is not None:status=running
            else:raise ValueError("running status without event")
            if status==0xff:
                meta=buf[at];at+=1;n,at=vlq(buf,at);payload=buf[at:at+n];at+=n
                if len(payload)!=n:raise ValueError("truncated meta event")
                if meta==0x51:
                    if n!=3:raise ValueError("invalid tempo event")
                    tempo=int.from_bytes(payload,"big")
                    if tempo<=0:raise ValueError("zero tempo")
                    tempos.append((tick,track,len(tempos),tempo))
                if meta==0x2f:break
            elif status in (0xf0,0xf7):
                n,at=vlq(buf,at);at+=n;running=None
            elif 0x80<=status<0xf0:
                running=status;kind=status&0xf0;channel=status&15
                n=1 if kind in (0xc0,0xd0) else 2;payload=buf[at:at+n];at+=n
                if len(payload)!=n or any(c>=128 for c in payload):raise ValueError("invalid channel event")
                if kind==0x90 and payload[1]>0:pending[(channel,payload[0])].append((tick,payload[1]))
                elif kind==0x80 or (kind==0x90 and payload[1]==0):
                    key=(channel,payload[0])
                    if not pending[key]:raise ValueError("unmatched note-off")
                    start,velocity=pending[key].popleft()
                    if tick<=start:raise ValueError("nonpositive note length")
                    notes.append((track,payload[0],start,tick,velocity,channel==9))
            else:raise ValueError("unsupported system event")
        if any(pending.values()):raise ValueError("unreleased note-on")
    if not 1<=len(notes)<=100_000:raise ValueError("note count out of budget")
    tempo_at={0:500_000};seen={}
    for tick,track,order,tempo in sorted(tempos):
        if tick in seen and seen[tick]!=tempo:raise ValueError("conflicting simultaneous tempos")
        seen[tick]=tempo;tempo_at[tick]=tempo
    ticks=sorted(tempo_at);values=[tempo_at[t] for t in ticks];elapsed=[0.0]
    for i in range(1,len(ticks)):elapsed.append(elapsed[-1]+(ticks[i]-ticks[i-1])*values[i-1]/division/1000)
    def metric(t):
        i=bisect.bisect_right(ticks,t)-1;return elapsed[i]+(t-ticks[i])*values[i]/division/1000
    converted=[dict(pitch=p,startMs=metric(s),durationMs=metric(e)-metric(s),track=tr,velocity=v,percussion=drum) for tr,p,s,e,v,drum in notes]
    if metric(last_tick)>1_800_000 or any(n['durationMs']>60_000 for n in converted):raise ValueError("duration out of budget")
    converted.sort(key=lambda n:(n['track'],n['startMs'],n['pitch'],n['durationMs'],n['velocity']))
    return dict(notes=converted,lengthMs=metric(last_tick),bpm=60_000_000/values[0],tempoChanges=len(ticks),ticksPerQuarter=division,durationKinds=len({round(n['durationMs'],3) for n in converted}),reference="independent Python SMF parser; no transcription")
