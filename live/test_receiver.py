import struct
import unittest
from receiver import Assembler,HEADER,CHUNK

def fragments(seq=1,session=1):
    data=b'x'*3000
    return [HEADER.pack(b'R3LP',session,seq,123,0,len(data),off,30)+data[off:off+CHUNK]
            for off in range(0,len(data),CHUNK)]
class TestReassembly(unittest.TestCase):
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
