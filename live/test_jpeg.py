"""Exercise the same embedded JPEG encoder with byte limits and rotated input."""
import io
import random
import unittest
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageDraw
from codec import Codec
from evaluate import fixture

class TestJPEG(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.codec=Codec()
    def test_colors_and_orientation(self):
        for w in (320,400):
            im=Image.new('RGB',(w,240),'blue')
            ImageDraw.Draw(im).rectangle((0,0,31,31),fill='red')
            data=self.codec.jpeg(im,12000)
            with Image.open(io.BytesIO(data)) as out:
                self.assertEqual(out.size,im.size)
                r,g,b=out.getpixel((8,8));self.assertGreater(r,220);self.assertLess(b,25)
                r,g,b=out.getpixel((8,220));self.assertGreater(b,220);self.assertLess(r,25)
    def test_hard_cap_and_failure(self):
        for w in (320,400):
            im=fixture(w,1)
            for cap in (1024,4000,9644,12055,40000):
                for quality in range(4):
                    data=self.codec.jpeg(im,cap,quality) # binding checks trailing canary even on failure
                    self.assertLessEqual(len(data),cap)
                    if data:
                        with Image.open(io.BytesIO(data)) as out:
                            out.load();self.assertEqual(out.size,im.size)
            self.assertEqual(self.codec.jpeg(im,1024,0),b'')
    def test_invalid_dimensions(self):
        self.assertEqual(self.codec.jpeg(Image.new('RGB',(401,240)),12000),b'')
    def test_large_r7_frame_and_capacity_canary(self):
        # High-detail input exceeds the R6 40 KB limit at Q95. The R7 shared
        # pair budget can give most bytes to either screen at 15 FPS / 2 MB/s.
        lib=self.codec.lib
        lib.live_jpeg_prepare.argtypes=[C.c_uint,C.c_void_p,C.c_uint,C.c_uint]
        lib.live_jpeg_render.argtypes=[C.c_uint,C.c_uint,C.c_void_p,C.c_size_t]
        lib.live_jpeg_render.restype=C.c_size_t
        for sc,w in enumerate((400,320)):
            im=Image.frombytes('RGB',(w,240),random.Random(w).randbytes(w*240*3))
            expected=self.codec.jpeg(im,128000,95,scaled=True)
            self.assertGreater(len(expected),40000)
            with Image.open(io.BytesIO(expected)) as decoded:
                decoded.load();self.assertEqual(decoded.size,(w,240))
            lib.live_jpeg_reset(sc);lib.live_jpeg_prepare(sc,self.codec.pack(im),w,240)
            out=C.create_string_buffer(b'\xa5'*128064)
            n=lib.live_jpeg_render(sc,95,out,128000)
            self.assertEqual(out.raw[:n],expected)
            self.assertEqual(out.raw[128000:128064],b'\xa5'*64)
            self.assertEqual(lib.live_jpeg_render(sc,95,out,128001),0)
            self.assertEqual(self.codec.jpeg(im,128001,95,scaled=True),b'')
    def test_cached_dct_is_exact_reusable_and_bounded(self):
        lib=self.codec.lib
        lib.live_jpeg_prepare.argtypes=[C.c_uint,C.c_void_p,C.c_uint,C.c_uint]
        lib.live_jpeg_render.argtypes=[C.c_uint,C.c_uint,C.c_void_p,C.c_size_t]
        lib.live_jpeg_render.restype=C.c_size_t
        for sc,w in enumerate((400,320)):
            lib.live_jpeg_reset(sc)
            out=C.create_string_buffer(b'\xa5'*40064)
            self.assertEqual(lib.live_jpeg_render(sc,60,out,40000),0)
            im=fixture(w,1);raw=self.codec.pack(im)
            self.assertEqual(lib.live_jpeg_prepare(sc,raw,w,240),w*240//256)
            self.assertEqual(lib.live_jpeg_prepare(sc,raw,w,240),0)
            for q in (1,10,40,60,85,95):
                expected=self.codec.jpeg(im,40000,q,scaled=True)
                n=lib.live_jpeg_render(sc,q,out,40000)
                self.assertEqual(out.raw[:n],expected)
                self.assertEqual(out.raw[40000:40064],b'\xa5'*64)
                small=C.create_string_buffer(b'\xa5'*1088)
                n=lib.live_jpeg_render(sc,q,small,1024)
                self.assertLessEqual(n,1024);self.assertEqual(small.raw[1024:],b'\xa5'*64+b'\0')
            im.putpixel((5,5),(255,255,255));raw=self.codec.pack(im)
            self.assertEqual(lib.live_jpeg_prepare(sc,raw,w,240),1)
            expected=self.codec.jpeg(im,40000,50,scaled=True)
            n=lib.live_jpeg_render(sc,50,out,40000)
            self.assertEqual(out.raw[:n],expected)
    def test_scaled_quantization_and_budget(self):
        for w in (320,400):
            im=fixture(w,0)
            sizes=[]
            for quality in (1,10,25,50,75,95):
                data=self.codec.jpeg(im,40000,quality,scaled=True)
                with Image.open(io.BytesIO(data)) as out:
                    out.load();self.assertEqual(out.size,im.size)
                    scale=5000//quality if quality<50 else 200-2*quality
                    self.assertEqual(out.quantization[0][0],max(1,min(255,(16*scale+50)//100)))
                    self.assertEqual(out.quantization[1][0],max(1,min(255,(17*scale+50)//100)))
                sizes.append(len(data))
                capped=self.codec.jpeg(im,4000,quality,scaled=True)
                self.assertLessEqual(len(capped),4000)
            self.assertGreater(sizes[-1],sizes[0])
            # At q50 the custom table is identical to the original medium table.
            self.assertEqual(self.codec.jpeg(im,40000,50,scaled=True),self.codec.jpeg(im,40000,2))
    def test_screen_contexts_encode_concurrently_without_cross_talk(self):
        fn=self.codec.lib.live_jpeg_encode_screen
        fn.argtypes=[C.c_uint,C.c_void_p,C.c_uint,C.c_uint,C.c_uint,C.c_void_p,C.c_size_t]
        fn.restype=C.c_size_t
        cases=[]
        for screen,w in enumerate((400,320)):
            im=fixture(w,screen);quality=(75,30)[screen]
            expected=self.codec.jpeg(im,40000,quality,scaled=True)
            cases.append((screen,w,quality,self.codec.pack(im),expected))
        def worker(case):
            screen,w,quality,raw,expected=case
            for _ in range(100):
                out=C.create_string_buffer(b'\xa5'*40064)
                n=fn(screen,raw,w,240,quality,out,40000)
                self.assertEqual(out.raw[:n],expected)
                self.assertEqual(out.raw[40000:40064],b'\xa5'*64)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(worker,cases))
        out=C.create_string_buffer(40000)
        self.assertEqual(fn(2,cases[0][3],400,240,75,out,40000),0)
    def test_cached_contexts_concurrent(self):
        lib=self.codec.lib
        lib.live_jpeg_prepare.argtypes=[C.c_uint,C.c_void_p,C.c_uint,C.c_uint]
        lib.live_jpeg_render.argtypes=[C.c_uint,C.c_uint,C.c_void_p,C.c_size_t];lib.live_jpeg_render.restype=C.c_size_t
        cases=[]
        for sc,w in enumerate((400,320)):
            im=fixture(w,sc);q=(75,30)[sc]
            cases.append((sc,w,self.codec.pack(im),q,self.codec.jpeg(im,40000,q,scaled=True)))
        def worker(case):
            sc,w,raw,q,expected=case;out=C.create_string_buffer(40000)
            lib.live_jpeg_reset(sc)
            for i in range(50):
                self.assertEqual(lib.live_jpeg_prepare(sc,raw,w,240),0 if i else w*240//256)
                n=lib.live_jpeg_render(sc,q,out,40000);self.assertEqual(out.raw[:n],expected)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(worker,cases))

if __name__=='__main__':unittest.main()
