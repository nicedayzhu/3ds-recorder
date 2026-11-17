"""Summarize /live-bench.csv from the physical New 3DS. Timings exclude DMA/network/game load."""
import argparse
import csv
from collections import defaultdict
import math
import statistics

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('csv');a=p.parse_args()
    groups=defaultdict(list)
    with open(a.csv,newline='') as f:
        for row in csv.DictReader(f):groups[(row['codec'],int(row['width']))].append(row)
    means={}
    for (codec,width),rows in groups.items():
        us=sorted(float(r['encode_us']) for r in rows)
        mean=statistics.mean(us);means[(codec,width)]=mean
        successes=sum(int(r['bytes'])>0 for r in rows)
        print(f'{codec:12s} {width}x240: mean={mean/1000:.2f} ms '
              f'p95={us[math.ceil(len(us)*.95)-1]/1000:.2f} ms max={max(us)/1000:.2f} ms '
              f'fits={successes}/{len(rows)}')
    for codec in dict.fromkeys(k[0] for k in groups):
        if all((codec,w) in means for w in (400,320)):
            ms=sum(means[(codec,w)] for w in (400,320))/1000
            print(f'{codec}: summed screen means={ms:.2f} ms; 30 FPS period=33.33 ms; 24 FPS=41.67 ms')
    print('Encoding-only necessary condition; not a measured game streaming FPS or end-to-end latency.')
if __name__=='__main__':main()
