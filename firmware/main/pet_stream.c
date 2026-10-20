#include "pet_stream.h"
#include <string.h>

void pet_sse_init(pet_sse_t *s, char *line, char *data, size_t capacity, pet_sse_event_fn event, void *user)
{
    *s = (pet_sse_t){.line=line,.data=data,.capacity=capacity,.event=event,.user=user};
    if (!line || !data || capacity<2 || !event) s->failed=true;
}
static bool line_done(pet_sse_t *s)
{
    size_t n=s->line_used;
    if(n && s->line[n-1]=='\r') n--;
    s->line[n]=0; s->line_used=0;
    if(!n) {
        if(!s->data_used) return true;
        s->data[--s->data_used]=0; /* Last data line's joining newline. */
        bool ok=s->event(s->data,s->data_used,s->user); s->data_used=0;
        return ok;
    }
    if(n<5 || memcmp(s->line,"data:",5)) return true; /* comments/id/event/retry */
    size_t start=5;if(start<n && s->line[start]==' ')start++;
    size_t count=n-start;
    if(count+s->data_used+2>s->capacity) return false;
    memcpy(s->data+s->data_used,s->line+start,count);s->data_used+=count;
    s->data[s->data_used++]='\n';s->data[s->data_used]=0;return true;
}
bool pet_sse_feed(pet_sse_t *s,const void *bytes,size_t length)
{
    if(s->failed || (!bytes && length))return false;
    const unsigned char *p=bytes;
    for(size_t i=0;i<length;i++) {
        if(!p[i]){s->failed=true;return false;}
        if(p[i]=='\n') {if(!line_done(s)){s->failed=true;return false;}}
        else {if(s->line_used+1>=s->capacity){s->failed=true;return false;}s->line[s->line_used++]=(char)p[i];}
    }
    return true;
}
bool pet_sse_complete(const pet_sse_t *s){return !s->failed && !s->line_used && !s->data_used;}
