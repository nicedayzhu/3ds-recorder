"""R6 atomic dual-screen reassembly with bounded striped XOR recovery."""
from collections import deque
import struct

HEADER=struct.Struct('<4s7I')
CONFIG=struct.Struct('<4s4I')
CHUNK=1168
STRIPES=2

def newer(a,b):return 0<((a-b)&0xffffffff)<0x80000000

def config_packet(session,sequence,fps,rate):
    if fps not in (24,30) or not 620000<=rate<=1000000:raise ValueError('Invalid FPS or rate')
    return CONFIG.pack(b'R6CF',session,sequence,fps,rate)

def packetize(top,bottom,session,sequence,pts,fps):
    """Reference packetizer for fault-injection QA; same layout as ARM sender."""
    screens=(top,bottom);parity=[[bytearray(CHUNK) for _ in range(STRIPES)] for _ in range(2)]
    for off in range(0,max(map(len,screens)),CHUNK):
        for sc,data in enumerate(screens):
            if off>=len(data):continue
            piece=data[off:off+CHUNK];stripe=parity[sc][off//CHUNK%STRIPES]
            for i,v in enumerate(piece):stripe[i]^=v
            yield HEADER.pack(b'R3P2',session,sequence,pts,sc,len(data),off,fps)+piece
    for group in range(STRIPES):
        for sc,data in enumerate(screens):
            yield HEADER.pack(b'R3F2',session,sequence,pts,sc,len(data),group,fps)+parity[sc][group]

class PairAssembler:
    def __init__(self):
        self.session=None;self.retired=deque(maxlen=16);self.frames={};self.latest=None;self.done=None
        self.metrics=dict.fromkeys(('udp_packets','invalid_packets','late_packets','duplicate_packets',
            'reordered_packets','incomplete_frames','missing_fragments','expired_frames','missing_one',
            'missing_two','missing_many','incomplete_pairs','complete_pairs','fec_recovered'),0)
    def discard(self,seq,expired=False):
        pair=self.frames.pop(seq);self.metrics['incomplete_pairs']+=1
        for frame in pair['screens']:
            if frame is None:
                self.metrics['incomplete_frames']+=1;continue
            missing=(frame['total']+CHUNK-1)//CHUNK-len(frame['parts'])
            if not missing:continue
            self.metrics['incomplete_frames']+=1;self.metrics['missing_fragments']+=missing
            self.metrics['expired_frames']+=int(expired)
            self.metrics['missing_one' if missing==1 else 'missing_two' if missing==2 else 'missing_many']+=1
    def expire(self,now):
        for seq,pair in list(self.frames.items()):
            if now-pair['time']>.080:self.discard(seq,True)
    def feed(self,packet,now):
        self.metrics['udp_packets']+=1;self.expire(now)
        if len(packet)<HEADER.size:
            self.metrics['invalid_packets']+=1;return None
        magic,session,seq,pts,sc,total,offset,fps=HEADER.unpack_from(packet);data=packet[HEADER.size:]
        parity=magic==b'R3F2'
        if (magic not in (b'R3P2',b'R3F2') or sc>1 or fps not in (24,30) or not 12<=total<=40000
            or (parity and (offset>=STRIPES or len(data)!=CHUNK))
            or (not parity and (offset>=total or offset%CHUNK or len(data)!=min(CHUNK,total-offset)))):
            self.metrics['invalid_packets']+=1;return None
        if session!=self.session:
            if parity or offset or session in self.retired:return None
            if self.session is not None:self.retired.append(self.session)
            self.session=session;self.frames.clear();self.latest=None;self.done=None
        if self.done is not None and not newer(seq,self.done):
            self.metrics['duplicate_packets' if seq==self.done else 'late_packets']+=1;return None
        if seq not in self.frames:
            if self.latest is not None and not newer(seq,self.latest):
                self.metrics['late_packets']+=1;return None
            self.latest=seq
            while len(self.frames)>=2:self.discard(next(iter(self.frames)))
            self.frames[seq]=dict(time=now,pts=pts,fps=fps,screens=[None,None])
        pair=self.frames[seq]
        if pair['pts']!=pts or pair['fps']!=fps:
            self.metrics['invalid_packets']+=1;return None
        frame=pair['screens'][sc]
        if frame is None:frame=dict(total=total,parts={},parity={});pair['screens'][sc]=frame
        if frame['total']!=total:
            self.metrics['invalid_packets']+=1;return None
        collection=frame['parity'] if parity else frame['parts'];index=offset if parity else offset//CHUNK
        if index in collection:
            self.metrics['duplicate_packets']+=1;return None
        if not parity and collection and index<max(collection):self.metrics['reordered_packets']+=1
        collection[index]=data
        count=(total+CHUNK-1)//CHUNK
        for group,xor in frame['parity'].items():
            missing=[i for i in range(group,count,STRIPES) if i not in frame['parts']]
            if len(missing)!=1:continue
            recovered=bytearray(xor)
            for i in range(group,count,STRIPES):
                if i==missing[0]:continue
                for j,v in enumerate(frame['parts'][i]):recovered[j]^=v
            i=missing[0];frame['parts'][i]=bytes(recovered[:min(CHUNK,total-i*CHUNK)])
            self.metrics['fec_recovered']+=1
        if not all(f is not None and len(f['parts'])==(f['total']+CHUNK-1)//CHUNK for f in pair['screens']):return None
        result=tuple(b''.join(f['parts'][i] for i in range(len(f['parts']))) for f in pair['screens'])
        self.frames.pop(seq);self.done=seq;self.metrics['complete_pairs']+=1
        for old in list(self.frames):
            if not newer(old,seq):self.discard(old)
        return result,session,seq,pts,fps
