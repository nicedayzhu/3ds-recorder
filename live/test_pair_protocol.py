import random
import unittest
from pair_protocol import PairAssembler,packetize,HEADER,CHUNK,config_packet,MAX_FRAME,FPS_OPTIONS

class TestPairs(unittest.TestCase):
    def setUp(self):
        rng=random.Random(71);self.top=rng.randbytes(9001);self.bottom=rng.randbytes(6007)
    def packets(self,seq=1,session=1,pts=123):return list(packetize(self.top,self.bottom,session,seq,pts,30))
    def feed(self,a,packets,start=0):
        results=[]
        for i,p in enumerate(packets):
            result=a.feed(p,start+i*.001)
            if result:results.append(result)
        return results
    def test_atomic_and_exact(self):
        a=PairAssembler();p=self.packets()
        top=[x for x in p if HEADER.unpack_from(x)[4]==0]
        bottom=[x for x in p if HEADER.unpack_from(x)[4]==1]
        self.assertEqual(self.feed(a,top),[])
        result=self.feed(a,bottom,.02)
        self.assertEqual(len(result),1);self.assertEqual(result[0][0],(self.top,self.bottom))
        self.assertEqual(a.metrics['complete_pairs'],1)
    def test_every_single_loss_and_recoverable_burst(self):
        packets=self.packets(2)
        for lost in range(len(packets)):
            a=PairAssembler();self.feed(a,self.packets())
            result=self.feed(a,[p for i,p in enumerate(packets) if i!=lost],.04)
            self.assertEqual(len(result),1);self.assertEqual(result[0][0],(self.top,self.bottom))
        a=PairAssembler();self.feed(a,self.packets())
        # Four interleaved data packets = two different stripes in each screen.
        result=self.feed(a,packets[:4]+packets[8:],.04)
        self.assertEqual(result[0][0],(self.top,self.bottom));self.assertEqual(a.metrics['fec_recovered'],4)
    def test_unrecoverable_pair_never_mixes_next_and_queue_bounded(self):
        a=PairAssembler();self.feed(a,self.packets())
        p=[x for x in self.packets(2) if not (HEADER.unpack_from(x)[4]==1 and HEADER.unpack_from(x)[6] in (0,2*CHUNK))]
        self.assertEqual(self.feed(a,p,.04),[])
        result=self.feed(a,self.packets(3),.08)
        self.assertEqual(len(result),1);self.assertEqual(result[0][2],3)
        self.assertEqual(a.metrics['incomplete_pairs'],1)
        for seq in range(4,20):
            a.feed(self.packets(seq)[0],seq*.02);self.assertLessEqual(len(a.frames),2)
        a.expire(10);self.assertEqual(a.frames,{})
    def test_wrap_retired_sessions_and_reorder(self):
        a=PairAssembler();self.feed(a,self.packets(0xffffffff))
        p=self.packets(0);result=self.feed(a,p[:1]+list(reversed(p[1:])),.04)
        self.assertEqual(len(result),1);self.assertEqual(result[0][0],(self.top,self.bottom))
        self.feed(a,self.packets(1,2),.08)
        self.assertEqual(self.feed(a,self.packets(2,1),.12),[])
        self.assertEqual(a.session,2)
    def test_metadata_corruption_and_cap(self):
        a=PairAssembler();p=self.packets();a.feed(p[0],0)
        bad=bytearray(p[1]);bad[12]^=1
        self.assertIsNone(a.feed(bad,.001));self.assertEqual(a.metrics['invalid_packets'],1)
        for total,offset in ((MAX_FRAME+1,0),(1,0),(9001,99999)):
            bad=HEADER.pack(b'R3F2',1,1,123,0,total,offset,30)+bytes(CHUNK)
            self.assertIsNone(a.feed(bad,.002))
    def test_configuration_hard_bounds(self):
        self.assertEqual(len(config_packet(1,1,24,1000000)),20)
        for hz in FPS_OPTIONS:
            for rate in (400000,1000000,2000000):self.assertEqual(len(config_packet(1,1,hz,rate)),20)
        for hz,rate in ((60,800000),(30,2000001),(24,399999)):
            with self.assertRaises(ValueError):config_packet(1,1,hz,rate)
    def test_larger_frames_and_new_fps_recover_exactly(self):
        for fps in FPS_OPTIONS:
            a=PairAssembler();self.top=bytes(range(256))*300;self.bottom=bytes(range(255,-1,-1))*180
            packets=list(packetize(self.top,self.bottom,1,1,0,fps))
            packets=packets[:4]+packets[8:]
            result=None
            for i,p in enumerate(packets):
                value=a.feed(p,i*.0002)
                if value:result=value
            self.assertIsNotNone(result);self.assertEqual(result[0],(self.top,self.bottom))
            self.assertEqual(a.metrics['fec_recovered'],4)

if __name__=='__main__':unittest.main()
