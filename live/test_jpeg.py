"""Exercise the same embedded JPEG encoder with byte limits and rotated input."""
import io
import unittest
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

if __name__=='__main__':unittest.main()
