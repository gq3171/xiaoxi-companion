#include "pet_asset_codec.h"
#ifdef ESP_PLATFORM
#include "miniz.h"
#include "pet_util.h"
static tinfl_decompressor *s_decoder;
#else
#include <zlib.h>
#endif

bool pet_asset_expand_room(const uint16_t *source,uint16_t *target)
{
    if(!source||!target||source==target)return false;
    for(unsigned y=0;y<480;y++){
        unsigned sy=y*2/3,fy=y*2%3,ny=sy<319?sy+1:sy;
        for(unsigned x=0;x<480;x++){
            unsigned sx=x*2/3,fx=x*2%3,nx=sx<319?sx+1:sx;
            uint16_t p[4]={source[sy*320+sx],source[sy*320+nx],source[ny*320+sx],source[ny*320+nx]};
            unsigned w[4]={(3-fx)*(3-fy),fx*(3-fy),(3-fx)*fy,fx*fy};
            unsigned r=0,g=0,b=0;
            for(int i=0;i<4;i++){r+=((p[i]>>11)&31)*w[i];g+=((p[i]>>5)&63)*w[i];b+=(p[i]&31)*w[i];}
            target[y*480+x]=(uint16_t)(((r+4)/9<<11)|((g+4)/9<<5)|(b+4)/9);
        }
    }
    return true;
}

bool pet_asset_inflate(const uint8_t *input, size_t size, uint8_t *output, size_t expected)
{
    if (!input || !output || !size || !expected || expected > 320 * 320 * 2) return false;
#ifdef ESP_PLATFORM
    /* The ROM convenience API places a large decoder on the caller's stack.
     * Keep it in PSRAM instead of overflowing LVGL's small task stack. */
    if (!s_decoder) s_decoder = pet_alloc(sizeof(*s_decoder));
    if (!s_decoder) return false;
    tinfl_init(s_decoder);
    size_t used = size, written = expected;
    tinfl_status result = tinfl_decompress(s_decoder, input, &used, output, output, &written,
        TINFL_FLAG_PARSE_ZLIB_HEADER | TINFL_FLAG_USING_NON_WRAPPING_OUTPUT_BUF | TINFL_FLAG_COMPUTE_ADLER32);
    return result == TINFL_STATUS_DONE && used == size && written == expected;
#else
    uLongf written = expected; uLong used = size;
    return uncompress2(output, &written, input, &used) == Z_OK && written == expected && used == size;
#endif
}
