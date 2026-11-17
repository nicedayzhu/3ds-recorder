#include "live_rate.h"
#include <assert.h>
#include <stdio.h>
int main(void) {
    LiveRate c;live_rate_init(&c,1000000);assert(c.current==800000);
    assert(live_rate_update(&c,600,350,30,20,100)==680000);
    for(unsigned i=0;i<20;i++)live_rate_update(&c,600,350,30,20,100);
    assert(c.current==400000);
    assert(live_rate_update(&c,300,300,60,0,10)==400000);
    assert(live_rate_update(&c,300,300,60,0,10)==400000);
    assert(live_rate_update(&c,300,300,60,0,10)==410000);
    for(unsigned i=0;i<1000;i++)live_rate_update(&c,300,300,60,0,10);
    assert(c.current==1000000);
    assert(live_rate_update(&c,300,300,60,0,80)==900000);
    assert(live_rate_update(&c,0,0,0,0,999)==900000);
    assert(live_rate_update(&c,600,0,0,0,0)==765000);
    live_rate_init(&c,620000);assert(c.current==620000);
    for(unsigned i=0;i<100;i++)live_rate_update(&c,300,300,60,0,10);
    assert(c.current==620000);
    puts("adaptive rate: loss, delay, floor, gradual recovery and cap OK");return 0;
}
