import struct
import unittest
from receiver import Assembler,HEADER,CHUNK,write_frame,RelativeDelay,compose,STATUS,parse_status

def fragments(seq=1,session=1):
    data=b'x'*3000
    return [HEADER.pack(b'R3LP',session,seq,123,0,len(data),off,30)+data[off:off+CHUNK]
            for off in range(0,len(data),CHUNK)]
class TestReassembly(unittest.TestCase):
    def test_status_bounds_and_separate_protocol(self):
        values=[123,1000,1000000,800000,30,30,30,29,29,0,0,1,2,3,22000,18000]
        packet=STATUS.pack(b'R3ST',*values)
        self.assertEqual(parse_status(packet)['sender_budget'],800000)
        self.assertIsNone(parse_status(packet[:-1]))
        self.assertIsNone(parse_status(b'R3LP'+packet[4:]))
        values[3]=1000001;self.assertIsNone(parse_status(STATUS.pack(b'R3ST',*values)))
        values[3]=800000;values[4]=60;self.assertIsNone(parse_status(STATUS.pack(b'R3ST',*values)))
    def test_relative_delay_wrap_and_session_reset(self):
        d=RelativeDelay()
        self.assertEqual(d.sample(1,0xfffffff0,10),0)
        self.assertAlmostEqual(d.sample(1,0x00000010,10.020032),20)
        self.assertAlmostEqual(d.sample(1,0xfffffff8,10.020040),20.032)
        self.assertEqual(d.sample(2,1234,99),0)
    def test_composition_keeps_screen_pixels_and_bottom_borders(self):
        top=b'\x10\x20\x30'*(400*240);bottom=b'\x40\x50\x60'*(320*240)
        out=compose(top,bottom)
        self.assertEqual(len(out),400*480*3);self.assertEqual(out[:len(top)],top)
        for y in (240,479):
            row=out[y*1200:(y+1)*1200]
            self.assertEqual(row[:120],bytes(120));self.assertEqual(row[120:1080],bottom[:960])
            self.assertEqual(row[1080:],bytes(120))
    def test_short_pipe_writes(self):
        class Pipe:
            def __init__(self):self.data=bytearray()
            def write(self,data):
                count=min(17,len(data));self.data.extend(data[:count]);return count
        pipe=Pipe();frame=bytes(range(256));write_frame(pipe,frame)
        self.assertEqual(pipe.data,frame)
    def test_reorder_duplicate_and_late(self):
        a=Assembler();p=fragments();self.assertIsNone(a.feed(p[0],0))
        self.assertIsNone(a.feed(p[2],.01));self.assertIsNone(a.feed(p[2],.02))
        self.assertEqual(a.feed(p[1],.03),(0,b'x'*3000));self.assertIsNone(a.feed(p[1],.04))
        self.assertIsNone(a.feed(fragments(0)[0],.05))
    def test_loss_recovers_on_next_frame(self):
        a=Assembler();p=fragments();a.feed(p[0],0);a.feed(p[2],.01)
        out=None
        for p in fragments(2):out=a.feed(p,.05)
        self.assertEqual(out,(0,b'x'*3000))
        self.assertEqual(a.metrics['incomplete_frames'],1)
        self.assertEqual(a.metrics['missing_fragments'],1)
        self.assertEqual(a.metrics['missing_one'],1)
    def test_loss_metrics_distinguish_reorder_from_missing(self):
        a=Assembler();p=fragments()
        for i in (0,2,2,1):a.feed(p[i],.01)
        self.assertEqual(a.metrics['reordered_packets'],1)
        self.assertEqual(a.metrics['duplicate_packets'],1)
        for packet in fragments(2):a.feed(packet,.02)
        a.feed(p[0],.03)
        self.assertEqual(a.metrics['late_packets'],1)
        self.assertEqual(a.metrics['missing_fragments'],0)
    def test_expiry_counted_only_once(self):
        a=Assembler();p=fragments();a.feed(p[0],0)
        a.feed(p[1],.2);a.feed(p[2],.21)
        for packet in fragments(2):a.feed(packet,.3)
        self.assertEqual(a.metrics['incomplete_frames'],1)
        self.assertEqual(a.metrics['expired_frames'],1)
        self.assertEqual(a.metrics['missing_fragments'],2)
    def test_invalid_and_timeout(self):
        a=Assembler();p=fragments();self.assertIsNone(a.feed(p[0],0))
        self.assertIsNone(a.feed(p[1],1));self.assertIsNone(a.feed(p[2],1))
        self.assertIsNone(a.feed(b'',1));bad=bytearray(p[0]);struct.pack_into('<I',bad,20,0xffffffff)
        self.assertIsNone(a.feed(bad,1))
    def test_restart_does_not_revert_to_retired_session(self):
        a=Assembler()
        for p in fragments(9,1):a.feed(p,0)
        self.assertIsNone(a.feed(fragments(1,2)[0],.01))
        self.assertIsNone(a.feed(fragments(10,1)[0],.02))
        self.assertEqual(a.session,2)
    def test_sequence_wrap(self):
        a=Assembler()
        for p in fragments(0xffffffff):a.feed(p,0)
        result=None
        for p in fragments(0):result=a.feed(p,.01)
        self.assertEqual(result,(0,b'x'*3000))
if __name__=='__main__':unittest.main()
