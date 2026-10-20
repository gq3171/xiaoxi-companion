/* Execute the existing evidence-checked firmware memory engine on Linux.
 * SQLite owns persistence and idempotency; this module is a pure state reducer.
 * The caller must serialize load/query/apply/dump under one process-wide lock. */
#include <stdlib.h>
#include <string.h>
#include "pet_memory.c"

int brain_load(const char *json)
{
    cJSON *next=cJSON_Parse(json);
    const char *required[]={"cards","history","pending","growth","outcomes","changes"};
    if(!cJSON_IsObject(next)){cJSON_Delete(next);return -1;}
    for(size_t i=0;i<sizeof(required)/sizeof(required[0]);i++){
        cJSON *v=cJSON_GetObjectItemCaseSensitive(next,required[i]);
        if(!v)cJSON_AddArrayToObject(next,required[i]);
        else if(!cJSON_IsArray(v)){cJSON_Delete(next);return -1;}
    }
    if(!cJSON_IsNumber(cJSON_GetObjectItem(next,"next_id"))){cJSON_Delete(next);return -1;}
    if(!cJSON_GetObjectItem(next,"summary"))cJSON_AddStringToObject(next,"summary","");
    cJSON_Delete(s_memory);s_memory=next;return 0;
}
char *brain_dump(void){return cJSON_PrintUnformatted(s_memory);}
void brain_free(void *p){free(p);}
char *brain_query(const char *query)
{
    char context[16000];pet_memory_context(query,context,sizeof(context));
    cJSON *out=cJSON_CreateObject();
    cJSON_AddStringToObject(out,"context",context);
    cJSON_AddItemToObject(out,"history",pet_memory_history());
    char *request=pet_memory_reflection_request();
    cJSON_AddStringToObject(out,"reflection_request",request?request:"");free(request);
    cJSON_AddBoolToObject(out,"needs_reflection",pet_memory_needs_reflection());
    char *result=cJSON_PrintUnformatted(out);cJSON_Delete(out);return result;
}
int brain_apply(const char *raw)
{
    cJSON *op=cJSON_Parse(raw);if(!cJSON_IsObject(op)){cJSON_Delete(op);return -1;}
    const char *kind=str(op,"kind");int result=-1;
    if(!strcmp(kind,"add"))result=pet_memory_add(str(op,"role"),str(op,"text"),cJSON_IsTrue(cJSON_GetObjectItem(op,"owner")));
    else if(!strcmp(kind,"observe"))result=pet_memory_observe(str(op,"event"),str(op,"text"));
    else if(!strcmp(kind,"reflection"))result=pet_memory_apply_reflection(str(op,"json"));
    else if(!strcmp(kind,"clear_pending"))result=pet_memory_clear_pending();
    else if(!strcmp(kind,"ignore"))result=pet_memory_ignore_message(number(op,"id",-1));
    cJSON_Delete(op);return result;
}
