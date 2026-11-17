#include <assert.h>
#include <stdio.h>
#include "live_pair.h"
int main(void) {
    const unsigned rates[]={400000,500000,600000,620000,700000,800000,900000,1000000,1200000,1400000,1600000,1800000,2000000};
    const unsigned frame_rates[]={15,20,24,30};
    for(unsigned ri=0;ri<sizeof rates/sizeof rates[0];ri++)for(unsigned fi=0;fi<4;fi++) {
        unsigned rate=rates[ri],fps=frame_rates[fi];
        assert(live_valid_fps(fps));
        unsigned budget=live_pair_budget(rate,fps);
        assert(budget<=128000);
        for(unsigned top=1024;top<budget-1024;top++) {
            unsigned bottom=budget-top;
            assert((uint64_t)(live_screen_wire(top)+live_screen_wire(bottom))*fps+104<=rate);
        }
        for(unsigned q=2;q<=95;q++)assert(live_lower_quality(q,budget+1,budget)<q);
    }
    assert(!live_valid_fps(60)&&!live_valid_fps(0));
    puts("pair budget: all splits, parity, headers and status fit fixed rate");return 0;
}
