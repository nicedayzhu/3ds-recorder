"""Compare LTC1, embedded JPEGENC and a host Pillow JPEG quality reference.
The embedded sweep is an offline quality ceiling, not runtime adaptive quality.
"""
import argparse
import csv
import io
import math
from pathlib import Path
import random
from PIL import Image,ImageDraw,ImageChops,ImageStat
from codec import Codec,ROOT

def fixture(w,k):
    im=Image.new('RGB',(w,240));d=ImageDraw.Draw(im)
    if k==0:
        for y in range(240):d.line((0,y,w,y),fill=(y,70,255-y))
        d.rectangle((20,40,180,170),fill=(240,180,20));d.text((25,50),'3DS live: 24 - 30 FPS',fill='black')
    else:
        rng=random.Random(k)
        for y in range(0,240,4):
            for x in range(0,w,4):d.rectangle((x,y,x+3,y+3),fill=tuple(rng.randrange(256) for _ in range(3)))
    return im
def psnr(a,b):
    stat=ImageStat.Stat(ImageChops.difference(a,b));mse=sum(x*x for x in stat.rms)/3
    return 99.0 if not mse else 10*math.log10(255**2/mse)
def main():
    p=argparse.ArgumentParser();p.add_argument('--images',type=Path);a=p.parse_args()
    out=ROOT/'live/results';out.mkdir(exist_ok=True);codec=Codec();rows=[]
    images=[(p.stem,Image.open(p).convert('RGB')) for p in sorted(a.images.glob('*.png'))] if a.images else [
        (f'synthetic_{w}_{k}',fixture(w,k)) for w in (400,320) for k in (0,1)]
    for name,im in images:
        if im.height!=240 or im.width not in (400,320):raise ValueError('Use native 400x240 or 320x240 frames')
        for fps in (24,30):
            for rate in (700000,1000000):
                budget=rate*93//100//fps*im.width//720
                data=codec.encode(im,budget);decoded=Image.frombytes('RGB',im.size,codec.decode(data))
                cost=len(data)+math.ceil(len(data)/1168)*60
                best=None
                for q in range(1,96):
                    jpg=io.BytesIO();im.save(jpg,format='JPEG',quality=q,subsampling=2)
                    if len(jpg.getvalue())<=budget:best=(q,jpg.getvalue())
                jpeg_psnr=psnr(im,Image.open(io.BytesIO(best[1])).convert('RGB')) if best else None
                embedded=None
                for q in range(4):
                    jpg=codec.jpeg(im,budget,q)
                    if jpg:
                        embedded=(q,jpg);break
                embedded_psnr=psnr(im,Image.open(io.BytesIO(embedded[1])).convert('RGB')) if embedded else None
                rows.append(dict(sample=name,fps=fps,rate=rate,bytes=len(data),budget=budget,ip_bytes=cost,
                                 ltc1_psnr=round(psnr(im,decoded),2),host_jpeg_psnr=round(jpeg_psnr,2) if best else '',
                                 host_jpeg_quality=best[0] if best else '',
                                 jpegenc_quality=embedded[0] if embedded else 'fallback',jpegenc_bytes=len(embedded[1]) if embedded else 0,
                                 jpegenc_psnr=round(embedded_psnr,2) if embedded else ''))
                if fps==30 and rate==700000:
                    im.save(out/f'{name}_original.png');decoded.save(out/f'{name}_ltc1.png')
                    if embedded:(out/f'{name}_jpegenc.jpg').write_bytes(embedded[1])
                    if name in ('re_top_02','re_bottom_02'):
                        (ROOT/'live/build'/('live-bench-top.rgb565' if im.width==400 else 'live-bench-bottom.rgb565')).write_bytes(codec.pack(im))
        print(f'{name}: evaluated 24/30 FPS at 700000/1000000 bytes/s',flush=True)
    with (out/'quality.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=rows[0].keys());writer.writeheader();writer.writerows(rows)
if __name__=='__main__':main()
