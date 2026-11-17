"""Host bindings for the exact C codec used on ARM11."""
import ctypes as C
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
class Scratch(C.Structure):
    _fields_ = [('data', (C.c_uint8*25)*1500), ('order', C.c_uint16*1500),
                ('gain', C.c_uint32*1500), ('base', (C.c_uint8*7)*1500)]

class Codec:
    def __init__(self):
        self.lib = C.CDLL(str(ROOT/'live/build'/('livecodec.dll' if sys.platform=='win32' else 'liblivecodec.so')))
        self.lib.live_encode.argtypes = [C.c_void_p,C.c_void_p,C.c_uint,C.c_uint,C.c_size_t,C.c_void_p,C.c_size_t]
        self.lib.live_encode.restype = C.c_size_t
        self.lib.live_decode.argtypes = [C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t]
        self.lib.live_decode.restype = C.c_int
        self.lib.live_jpeg_encode.argtypes=[C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t]
        self.lib.live_jpeg_encode.restype=C.c_size_t
        self.scratch = Scratch()
    @staticmethod
    def pack(image):
        w,h = image.size
        packed = bytearray(w*h*2)
        for i,(r,g,b) in enumerate(image.convert('RGB').getdata()):
            x,y=i%w,i//w
            v=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
            j=(x*h+h-1-y)*2
            packed[j]=v&255;packed[j+1]=v>>8
        return bytes(packed)
    def encode(self, image, budget):
        w,h=image.size
        raw=self.pack(image); out=C.create_string_buffer(40000)
        n=self.lib.live_encode(C.byref(self.scratch),raw,w,h,budget,out,len(out))
        if not n: raise ValueError('Frame dimensions or budget invalid')
        return out.raw[:n]
    def jpeg(self,image,budget,quality=2):
        raw=self.pack(image);out=C.create_string_buffer(b'\xa5'*(budget+64))
        n=self.lib.live_jpeg_encode(raw,*image.size,quality,out,budget)
        if out.raw[budget:budget+64]!=b'\xa5'*64:raise RuntimeError('JPEG wrote beyond budget')
        return out.raw[:n]
    def decode(self, packet):
        out=C.create_string_buffer(400*240*3)
        n=self.lib.live_decode(packet,len(packet),out,len(out))
        if n<0: raise ValueError('Malformed LTC1 frame')
        return out.raw[:n]
