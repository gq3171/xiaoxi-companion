#include "pet_memory.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "pet_util.h"
#ifdef ESP_PLATFORM
#include "sdkconfig.h"
#endif
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
#include "pet_brain.h"
#endif

#ifndef PET_STORAGE_ROOT
#define PET_STORAGE_ROOT "/spiffs"
#endif
#define MEMORY_BASE PET_STORAGE_ROOT "/memory"
#define MEMORY_LIMIT (64 * 1024)
#define CARD_LIMIT 48
#define HISTORY_LIMIT 24
#define PENDING_LIMIT 8
#define GROWTH_LIMIT 16
#define OUTCOME_LIMIT 8

static cJSON *s_memory;
static uint32_t s_sequence;

static const char *str(cJSON *object, const char *key)
{
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsString(value) ? value->valuestring : "";
}

static int number(cJSON *object, const char *key, int fallback)
{
    cJSON *value = cJSON_GetObjectItemCaseSensitive(object, key);
    return cJSON_IsNumber(value) ? value->valueint : fallback;
}

static cJSON *array(const char *key) { return cJSON_GetObjectItemCaseSensitive(s_memory, key); }

static int save(void)
{
    char *json;
    while (true) {
        json = cJSON_PrintUnformatted(s_memory);
        if (!json) return -1;
        if (strlen(json) <= MEMORY_LIMIT) break;
        free(json);
        /* Even pathological escaping cannot grow the flash store indefinitely. */
        if (cJSON_GetArraySize(array("history")) > 4) cJSON_DeleteItemFromArray(array("history"), 0);
        else if (cJSON_GetArraySize(array("changes"))) cJSON_DeleteItemFromArray(array("changes"), 0);
        else if (cJSON_GetArraySize(array("pending")) > 1) cJSON_DeleteItemFromArray(array("pending"), 0);
        else if (cJSON_GetArraySize(array("outcomes"))) cJSON_DeleteItemFromArray(array("outcomes"), 0);
        else if (cJSON_GetArraySize(array("growth"))) cJSON_DeleteItemFromArray(array("growth"), 0);
        else if (str(s_memory, "summary")[0]) cJSON_ReplaceItemInObject(s_memory, "summary", cJSON_CreateString(""));
        else if (cJSON_GetArraySize(array("cards"))) {
            int victim = 0, least = 100, i = 0; cJSON *card;
            cJSON_ArrayForEach(card, array("cards")) {
                int importance = number(card, "importance", 3) + (strcmp(str(card, "kind"), "episode") ? 10 : 0);
                if (importance < least) { least = importance; victim = i; } i++;
            }
            cJSON_DeleteItemFromArray(array("cards"), victim);
        } else return -1;
    }
    int result = pet_snapshot_save(MEMORY_BASE, json, MEMORY_LIMIT, &s_sequence);
    free(json);
    return result;
}

int pet_memory_start(void)
{
    cJSON_Delete(s_memory); s_memory = NULL;
    char *json = pet_snapshot_load(MEMORY_BASE, MEMORY_LIMIT, &s_sequence);
    if (!json && pet_snapshot_exists(MEMORY_BASE)) return -1;
    s_memory = json ? cJSON_Parse(json) : NULL;
    free(json);
    if (s_memory && (!cJSON_IsArray(array("cards")) || !cJSON_IsArray(array("history")) ||
                     !cJSON_IsArray(array("pending")))) {
        cJSON_Delete(s_memory); s_memory = NULL;
        return -1;
    }
    if (!s_memory) {
        s_memory = cJSON_CreateObject();
        cJSON_AddNumberToObject(s_memory, "version", 1);
        cJSON_AddNumberToObject(s_memory, "next_id", 1);
        cJSON_AddArrayToObject(s_memory, "cards");
        cJSON_AddArrayToObject(s_memory, "history");
        cJSON_AddArrayToObject(s_memory, "pending");
        cJSON_AddArrayToObject(s_memory, "changes");
        cJSON_AddStringToObject(s_memory, "summary", "");
    }
    if (s_memory) {
        const char *added[] = {"growth", "outcomes"};
        for (int i = 0; i < 2; i++) {
            if (!cJSON_HasObjectItem(s_memory, added[i])) cJSON_AddArrayToObject(s_memory, added[i]);
            else if (!cJSON_IsArray(array(added[i]))) cJSON_ReplaceItemInObject(s_memory, added[i], cJSON_CreateArray());
        }
    }
    return s_memory ? 0 : -1;
}

int pet_memory_add(const char *role, const char *text, bool owner)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    {
    if(!text||!text[0])return -1;
    char compact[1025];pet_utf8_copy(compact,sizeof(compact),text);
    cJSON *op=cJSON_CreateObject();cJSON_AddStringToObject(op,"kind","add");cJSON_AddStringToObject(op,"role",role);
    cJSON_AddStringToObject(op,"text",compact);cJSON_AddBoolToObject(op,"owner",owner);
    int result=pet_brain_memory(op);cJSON_Delete(op);return result;
    }
#endif
    if (!s_memory || !text || !text[0] || (strcmp(role, "user") && strcmp(role, "assistant"))) return -1;
    char compact[1025];
    pet_utf8_copy(compact, sizeof(compact), text);
    int id = number(s_memory, "next_id", 1);
    cJSON_SetNumberValue(cJSON_GetObjectItem(s_memory, "next_id"), id + 1);
    cJSON *message = cJSON_CreateObject();
    cJSON_AddNumberToObject(message, "id", id);
    cJSON_AddStringToObject(message, "role", role);
    cJSON_AddStringToObject(message, "content", compact);
    cJSON_AddNumberToObject(message, "at", (double)time(NULL));
    cJSON_AddBoolToObject(message, "owner", owner);
    cJSON_AddItemToArray(array("history"), message);
    while (cJSON_GetArraySize(array("history")) > HISTORY_LIMIT) cJSON_DeleteItemFromArray(array("history"), 0);
    if (owner && strcmp(role, "user") == 0) {
        cJSON_AddItemToArray(array("pending"), cJSON_Duplicate(message, true));
        while (cJSON_GetArraySize(array("pending")) > PENDING_LIMIT) cJSON_DeleteItemFromArray(array("pending"), 0);
    }
    return save() == 0 ? id : -1;
}

cJSON *pet_memory_history(void)
{
    cJSON *result = cJSON_CreateArray();
    cJSON *message;
    cJSON_ArrayForEach(message, array("history")) {
        cJSON *item = cJSON_CreateObject();
        cJSON_AddStringToObject(item, "role", str(message, "role"));
        char dated[1200];double at=cJSON_GetNumberValue(cJSON_GetObjectItem(message,"at"));
        snprintf(dated,sizeof(dated),"[记录时间戳=%.0f，当前=%.0f；历史内容] %s",at,(double)time(NULL),str(message,"content"));
        cJSON_AddStringToObject(item, "content", dated);
        cJSON_AddItemToArray(result, item);
    }
    return result;
}

/* UTF-8 codepoint pairs provide a small Chinese-friendly lexical index, rebuilt
 * from at most 48 short cards. No embedding model or growing database is needed. */
static int overlap(const char *query, const char *text)
{
    int score = 0;
    for (size_t i = 0; query[i];) {
        unsigned char c = query[i];
        size_t first = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
        size_t remain = strlen(query + i);
        if (first >= remain) break;
        c = query[i + first];
        size_t second = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
        size_t bytes = first + second;
        if (bytes <= remain && bytes <= 8) {
            char gram[9] = {0};
            memcpy(gram, query + i, bytes);
            if (strstr(text, gram)) score += first > 1 ? 3 : 1;
        }
        i += first;
    }
    return score;
}

void pet_memory_context(const char *query, char *out, size_t capacity)
{
    if (!capacity) return;
    out[0] = 0;
    if (!s_memory) return;
    int scores[CARD_LIMIT], indices[CARD_LIMIT];
    int n = cJSON_GetArraySize(array("cards"));
    if (n > CARD_LIMIT) n = CARD_LIMIT;
    for (int i = 0; i < n; i++) {
        cJSON *card = cJSON_GetArrayItem(array("cards"), i);
        bool core = strcmp(str(card, "kind"), "episode") != 0;
        scores[i] = (core ? 1000 : 0) + number(card, "importance", 3) * 10 +
                    overlap(query ? query : "", str(card, "text"));
        indices[i] = i;
    }
    for (int i = 0; i < n; i++) for (int j = i + 1; j < n; j++) {
        if (scores[indices[j]] > scores[indices[i]]) {
            int swap = indices[i]; indices[i] = indices[j]; indices[j] = swap;
        }
    }
    size_t used = 0;
    for (int i = 0; i < n; i++) {
        cJSON *card = cJSON_GetArrayItem(array("cards"), indices[i]);
        if (scores[indices[i]] < 1000 && overlap(query ? query : "", str(card, "text")) == 0 && i > 3) continue;
        char line[512];
        int count = snprintf(line, sizeof(line), "- [%s/%s] %s\n", str(card, "kind"), str(card, "slot"), str(card, "text"));
        if (count <= 0 || (size_t)count >= sizeof(line) || used + count >= capacity) continue;
        memcpy(out + used, line, count + 1); used += count;
    }
    const char *summary = str(s_memory, "summary");
    if (summary[0] && capacity - used > strlen(summary) + 40) {
        int count = snprintf(out + used, capacity - used, "相处摘要（可能过时）：%s\n", summary);
        if (count > 0) used += count;
    }
    int included = 0, growth_indices[GROWTH_LIMIT], growth_scores[GROWTH_LIMIT];
    int growth_count = cJSON_GetArraySize(array("growth"));
    if (growth_count > GROWTH_LIMIT) growth_count = GROWTH_LIMIT;
    for (int i = 0; i < growth_count; i++) {
        cJSON *card = cJSON_GetArrayItem(array("growth"), i);
        growth_indices[i] = i;
        /* Relevant experience wins over a pile of unrelated active lessons.
         * General expression habits remain useful even in a short reply. */
        int relevance=overlap(query ? query : "",str(card,"text"))+
            overlap(query ? query : "",str(card,"trigger"))+
            overlap(query ? query : "",str(card,"slot"));
        growth_scores[i] = relevance*20 + (number(card,"active",0)?30:0)+
            (!strcmp(str(card,"kind"),"lesson")?10:0)+(!strcmp(str(card,"kind"),"style")?20:0);
    }
    for (int i = 0; i < growth_count; i++) for (int j = i + 1; j < growth_count; j++) {
        if (growth_scores[growth_indices[j]] > growth_scores[growth_indices[i]]) {
            int tmp = growth_indices[i]; growth_indices[i] = growth_indices[j]; growth_indices[j] = tmp;
        }
    }
    for (int i = 0; i < growth_count && included < 6; i++) {
        cJSON *growth = cJSON_GetArrayItem(array("growth"), growth_indices[i]);
        char line[700];
        int count = snprintf(line, sizeof(line), "\n[我的成长/%s/%s] %s；适用：%s；检查：%s\n",
            str(growth, "kind"), number(growth, "active", 0) ? "已采用，可纠正" : "暂定，不宣称固定个性",
            str(growth, "text"), str(growth, "trigger"), str(growth, "check"));
        if (count <= 0 || (size_t)count >= sizeof(line) || used + count >= capacity) continue;
        memcpy(out + used, line, count + 1); used += count; included++;
    }
}

int pet_memory_observe(const char *kind, const char *detail)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    {
    if(!kind||!detail||!detail[0])return -1;
    char compact[257];pet_utf8_copy(compact,sizeof(compact),detail);
    cJSON *op=cJSON_CreateObject();cJSON_AddStringToObject(op,"kind","observe");cJSON_AddStringToObject(op,"event",kind);cJSON_AddStringToObject(op,"text",compact);
    int result=pet_brain_memory(op);cJSON_Delete(op);return result;
    }
#endif
    if (!s_memory || !kind || !detail || !detail[0] ||
        (strcmp(kind, "failure") && strcmp(kind, "success"))) return -1;
    int id = number(s_memory, "next_id", 1);
    cJSON_SetNumberValue(cJSON_GetObjectItem(s_memory, "next_id"), id + 1);
    char compact[257]; pet_utf8_copy(compact, sizeof(compact), detail);
    cJSON *event = cJSON_CreateObject();
    cJSON_AddNumberToObject(event, "id", id); cJSON_AddStringToObject(event, "kind", kind);
    cJSON_AddStringToObject(event, "detail", compact);
    cJSON_AddItemToArray(array("outcomes"), event);
    while (cJSON_GetArraySize(array("outcomes")) > OUTCOME_LIMIT) cJSON_DeleteItemFromArray(array("outcomes"), 0);
    return save() == 0 ? id : -1;
}

bool pet_memory_needs_reflection(void) { return s_memory && (cJSON_GetArraySize(array("pending")) > 0 || cJSON_GetArraySize(array("outcomes")) > 0); }

char *pet_memory_reflection_request(void)
{
    cJSON *request = cJSON_CreateObject();
    cJSON_AddItemToObject(request, "existing", cJSON_Duplicate(array("cards"), true));
    cJSON_AddItemToObject(request, "owner_messages", cJSON_Duplicate(array("pending"), true));
    cJSON_AddItemToObject(request, "growth", cJSON_Duplicate(array("growth"), true));
    cJSON_AddItemToObject(request, "outcomes", cJSON_Duplicate(array("outcomes"), true));
    cJSON_AddItemToObject(request, "recent_dialogue", cJSON_Duplicate(array("history"), true));
    cJSON_AddStringToObject(request, "previous_summary", str(s_memory, "summary"));
    char *json = cJSON_PrintUnformatted(request);
    cJSON_Delete(request);
    return json;
}

static cJSON *source_by_id(int id)
{
    cJSON *item;
    cJSON_ArrayForEach(item, array("pending")) if (number(item, "id", -1) == id) return item;
    return NULL;
}

static bool valid_kind(const char *kind)
{
    return !strcmp(kind, "profile") || !strcmp(kind, "preference") || !strcmp(kind, "boundary") ||
           !strcmp(kind, "style") || !strcmp(kind, "episode") || !strcmp(kind, "commitment");
}

static bool forget_requested(const char *source)
{
    return strstr(source, "忘记") || strstr(source, "忘掉") || strstr(source, "别记") || strstr(source, "不要记");
}

static void archive(cJSON *card)
{
    cJSON *changes = array("changes");
    if (!cJSON_IsArray(changes)) changes = cJSON_AddArrayToObject(s_memory, "changes");
    cJSON_AddItemToArray(changes, cJSON_Duplicate(card, true));
    while (cJSON_GetArraySize(changes) > 8) cJSON_DeleteItemFromArray(changes, 0);
}

static cJSON *outcome_by_id(int id)
{
    cJSON *item;
    cJSON_ArrayForEach(item, array("outcomes")) if (number(item, "id", -1) == id) return item;
    return NULL;
}

static int apply_growth(cJSON *response)
{
    cJSON *ops = cJSON_GetObjectItem(response, "growth_ops");
    if (!ops) return 0;
    if (!cJSON_IsArray(ops) || cJSON_GetArraySize(ops) > 6) return -1;
    int accepted = 0; cJSON *op;
    cJSON_ArrayForEach(op, ops) {
        const char *kind = str(op, "kind"), *slot = str(op, "slot"), *action = str(op, "op");
        if ((strcmp(kind, "interest") && strcmp(kind, "style") && strcmp(kind, "lesson")) ||
            !slot[0] || strlen(slot) > 48) continue;
        cJSON *ids = cJSON_GetObjectItem(op, "source_ids");
        if (!cJSON_IsArray(ids) || !cJSON_GetArraySize(ids) || cJSON_GetArraySize(ids) > 4) continue;
        bool valid = true, owner_source = false, event_source = false, can_forget = false;
        cJSON *id;
        cJSON_ArrayForEach(id, ids) {
            if (!cJSON_IsNumber(id) || id->valueint != id->valuedouble) { valid = false; break; }
            cJSON *source = source_by_id(id->valueint), *event = outcome_by_id(id->valueint);
            if (!source && (!event || strcmp(kind, "lesson"))) { valid = false; break; }
            if (event) event_source = true;
            if (source) { owner_source = true; can_forget |= forget_requested(str(source, "content")); }
        }
        if (!valid) continue;
        int existing = -1, i = 0; cJSON *card;
        cJSON_ArrayForEach(card, array("growth")) {
            if (!strcmp(str(card, "kind"), kind) && !strcmp(str(card, "slot"), slot)) { existing = i; break; }
            i++;
        }
        if (!strcmp(action, "forget")) {
            if (existing >= 0 && can_forget) {
                cJSON_DeleteItemFromArray(array("growth"), existing); accepted++;
                cJSON_ReplaceItemInObject(s_memory, "history", cJSON_CreateArray());
                cJSON_ReplaceItemInObject(s_memory, "summary", cJSON_CreateString(""));
                cJSON_ReplaceItemInObject(s_memory, "changes", cJSON_CreateArray());
                cJSON_AddBoolToObject(response, "forgotten", true);
            }
            continue;
        }
        const char *text = str(op, "text"), *trigger = str(op, "trigger"), *check = str(op, "check"), *basis = str(op, "basis");
        bool correction = !strcmp(basis, "correction") && owner_source;
        if (strcmp(action, "upsert") || !text[0] || strlen(text) > 384 || !trigger[0] || strlen(trigger) > 96 ||
            !check[0] || strlen(check) > 96 ||
            (strcmp(basis, "correction") && strcmp(basis, "recurring") && strcmp(basis, "outcome")) ||
            (!strcmp(basis, "correction") && !owner_source) ||
            (!strcmp(basis, "outcome") && (strcmp(kind, "lesson") || !event_source)) ||
            (!strcmp(kind, "interest") && strcmp(basis, "recurring"))) continue;
        cJSON *old = existing >= 0 ? cJSON_GetArrayItem(array("growth"), existing) : NULL;
        bool same = old && !strcmp(str(old, "text"), text) && !strcmp(str(old, "trigger"), trigger) && !strcmp(str(old, "check"), check);
        cJSON *evidence = same ? cJSON_Duplicate(cJSON_GetObjectItem(old, "evidence"), true) : cJSON_CreateArray();
        if (!cJSON_IsArray(evidence)) { cJSON_Delete(evidence); evidence = cJSON_CreateArray(); }
        cJSON_ArrayForEach(id, ids) {
            bool seen = false; cJSON *previous;
            cJSON_ArrayForEach(previous, evidence) if (previous->valueint == id->valueint) seen = true;
            if (!seen && cJSON_GetArraySize(evidence) < 8) cJSON_AddItemToArray(evidence, cJSON_Duplicate(id, true));
        }
        bool active = !strcmp(kind, "interest") ? cJSON_GetArraySize(evidence) >= 2 :
            correction || !strcmp(basis, "outcome") || cJSON_GetArraySize(evidence) >= 2;
        cJSON *next = cJSON_CreateObject();
        cJSON_AddStringToObject(next, "kind", kind); cJSON_AddStringToObject(next, "slot", slot);
        cJSON_AddStringToObject(next, "text", text); cJSON_AddStringToObject(next, "trigger", trigger);
        cJSON_AddStringToObject(next, "check", check); cJSON_AddNumberToObject(next, "active", active);
        cJSON_AddItemToObject(next, "evidence", evidence);
        if (existing >= 0) { archive(old); cJSON_ReplaceItemInArray(array("growth"), existing, next); }
        else {
            if (cJSON_GetArraySize(array("growth")) >= GROWTH_LIMIT) {
                int victim = 0, index = 0; cJSON *item;
                cJSON_ArrayForEach(item, array("growth")) { if (!number(item, "active", 0)) { victim = index; break; } index++; }
                cJSON_DeleteItemFromArray(array("growth"), victim);
            }
            cJSON_AddItemToArray(array("growth"), next);
        }
        accepted++;
    }
    return accepted;
}

int pet_memory_apply_reflection(const char *json)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    {
    cJSON *op=cJSON_CreateObject();cJSON_AddStringToObject(op,"kind","reflection");cJSON_AddStringToObject(op,"json",json);
    int result=pet_brain_memory(op);cJSON_Delete(op);return result;
    }
#endif
    cJSON *response = cJSON_Parse(json);
    cJSON *ops = response ? cJSON_GetObjectItem(response, "ops") : NULL;
    if (!s_memory || !cJSON_IsArray(ops) || cJSON_GetArraySize(ops) > 8) { cJSON_Delete(response); return -1; }
    cJSON *growth_ops = cJSON_GetObjectItem(response, "growth_ops");
    if (growth_ops && (!cJSON_IsArray(growth_ops) || cJSON_GetArraySize(growth_ops) > 6)) { cJSON_Delete(response); return -1; }
    int accepted = apply_growth(response);
    cJSON *op;
    cJSON_ArrayForEach(op, ops) {
        cJSON *source = source_by_id(number(op, "source_id", -1));
        const char *slot = str(op, "slot"), *kind = str(op, "kind"), *text = str(op, "text");
        const char *action = str(op, "op");
        if (!source || !slot[0] || strlen(slot) > 48 || !valid_kind(kind)) continue;
        int existing = -1;
        cJSON *card;
        int index = 0;
        cJSON_ArrayForEach(card, array("cards")) {
            if (!strcmp(str(card, "slot"), slot) && !strcmp(str(card, "kind"), kind)) { existing = index; break; }
            index++;
        }
        if (!strcmp(action, "forget")) {
            if (existing >= 0 && forget_requested(str(source, "content"))) {
                cJSON_DeleteItemFromArray(array("cards"), existing); accepted++;
                cJSON_ReplaceItemInObject(s_memory, "history", cJSON_CreateArray());
                cJSON_ReplaceItemInObject(s_memory, "summary", cJSON_CreateString(""));
                cJSON_ReplaceItemInObject(s_memory, "changes", cJSON_CreateArray());
                cJSON_AddBoolToObject(response, "forgotten", true);
            }
            continue;
        }
        if (strcmp(action, "upsert") || !text[0] || strlen(text) > 384) continue;
        int importance = number(op, "importance", 3);
        if (importance < 1 || importance > 5) continue;
        cJSON *next = cJSON_CreateObject();
        cJSON_AddStringToObject(next, "slot", slot);
        cJSON_AddStringToObject(next, "kind", kind);
        cJSON_AddStringToObject(next, "text", text);
        cJSON_AddNumberToObject(next, "importance", importance);
        cJSON_AddNumberToObject(next, "source_id", number(source, "id", 0));
        cJSON_AddNumberToObject(next, "at", number(source, "at", 0));
        if (existing >= 0) {
            archive(cJSON_GetArrayItem(array("cards"), existing));
            cJSON_ReplaceItemInArray(array("cards"), existing, next);
        } else {
            if (cJSON_GetArraySize(array("cards")) >= CARD_LIMIT) {
                int victim = -1, lowest = 10000, i = 0;
                cJSON_ArrayForEach(card, array("cards")) {
                    int weight = number(card, "importance", 3) + (strcmp(str(card, "kind"), "episode") ? 10 : 0);
                    if (weight < lowest) { lowest = weight; victim = i; }
                    i++;
                }
                if (lowest > importance + (strcmp(kind, "episode") ? 10 : 0)) { cJSON_Delete(next); continue; }
                cJSON_DeleteItemFromArray(array("cards"), victim);
            }
            cJSON_AddItemToArray(array("cards"), next);
        }
        accepted++;
    }
    const char *summary = str(response, "summary");
    if (!cJSON_IsTrue(cJSON_GetObjectItem(response, "forgotten")) && summary[0] && strlen(summary) <= 4096) {
        cJSON_ReplaceItemInObject(s_memory, "summary", cJSON_CreateString(summary));
    }
    cJSON_Delete(response);
    /* Once reflection completed, bounded recent history carries short-term detail. */
    cJSON_ReplaceItemInObject(s_memory, "pending", cJSON_CreateArray());
    cJSON_ReplaceItemInObject(s_memory, "outcomes", cJSON_CreateArray());
    return save() == 0 ? accepted : -1;
}

int pet_memory_clear_pending(void)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    {
    cJSON *op=cJSON_CreateObject();cJSON_AddStringToObject(op,"kind","clear_pending");int result=pet_brain_memory(op);cJSON_Delete(op);return result;
    }
#endif
    cJSON_ReplaceItemInObject(s_memory, "pending", cJSON_CreateArray());
    return save();
}

int pet_memory_ignore_message(int id)
{
#ifdef CONFIG_DESKPET_REMOTE_BRAIN
    {
    cJSON *op=cJSON_CreateObject();cJSON_AddStringToObject(op,"kind","ignore");cJSON_AddNumberToObject(op,"id",id);int result=pet_brain_memory(op);cJSON_Delete(op);return result;
    }
#endif
    const char *keys[] = {"history", "pending"};
    for (int k = 0; k < 2; k++) {
        cJSON *items = array(keys[k]);
        for (int i = cJSON_GetArraySize(items) - 1; i >= 0; i--) {
            if (number(cJSON_GetArrayItem(items, i), "id", -1) == id) cJSON_DeleteItemFromArray(items, i);
        }
    }
    return save();
}

int pet_memory_reject_sources(const pet_memory_rejection_t *sources,size_t count)
{
    if(!s_memory || !sources || !count || count>24)return -1;
    int rejected[24],n=0;
    cJSON *message;
    cJSON_ArrayForEach(message,array("history")) {
        const char *text=str(message,"content");
        for(size_t j=0;j<count;j++)if(number(message,"id",-1)==sources[j].id &&
            pet_crc32(text,strlen(text))==sources[j].content_crc) {
            rejected[n++]=sources[j].id;break;
        }
    }
    if(!n)return 0;
    cJSON *before=cJSON_Duplicate(s_memory,true);if(!before)return -1;
    const char *keys[]={"history","pending","cards","growth","changes"};
    for(size_t k=0;k<sizeof(keys)/sizeof(keys[0]);k++) {
        cJSON *items=array(keys[k]);
        for(int i=cJSON_GetArraySize(items)-1;i>=0;i--) {
            cJSON *item=cJSON_GetArrayItem(items,i);bool remove=false;
            for(int j=0;j<n;j++) {
                if((k<2 && number(item,"id",-1)==rejected[j]) ||
                    (k>=2 && number(item,"source_id",-1)==rejected[j]))remove=true;
                cJSON *id;cJSON_ArrayForEach(id,cJSON_GetObjectItem(item,"evidence"))
                    if(cJSON_IsNumber(id) && id->valueint==rejected[j])remove=true;
            }
            if(remove)cJSON_DeleteItemFromArray(items,i);
        }
    }
    cJSON_ReplaceItemInObject(s_memory,"summary",cJSON_CreateString(""));
    if(save()!=0){cJSON_Delete(s_memory);s_memory=before;return -1;}
    cJSON_Delete(before);return n;
}

char *pet_memory_export(void){return s_memory?cJSON_PrintUnformatted(s_memory):NULL;}
int pet_memory_install_remote(const cJSON *snapshot)
{
    if(!cJSON_IsObject(snapshot)||!cJSON_IsArray(cJSON_GetObjectItem(snapshot,"history"))||
       !cJSON_IsArray(cJSON_GetObjectItem(snapshot,"cards"))||!cJSON_IsArray(cJSON_GetObjectItem(snapshot,"pending")))return -1;
    char *raw=cJSON_PrintUnformatted(snapshot);if(!raw||strlen(raw)>MEMORY_LIMIT){free(raw);return -1;}free(raw);
    cJSON *next=cJSON_Duplicate(snapshot,true);if(!next)return -1;
    cJSON *before=s_memory;s_memory=next;
    if(save()!=0){s_memory=before;cJSON_Delete(next);return -1;}
    cJSON_Delete(before);return 0;
}
