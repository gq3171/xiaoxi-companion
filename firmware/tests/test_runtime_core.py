"""Run actual platform-independent C modules against temporary flash files."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest

FIRMWARE = Path(__file__).resolve().parents[1]
MAIN = FIRMWARE / "main"
CJSON = FIRMWARE / "managed_components/espressif__cjson/cJSON"


class RuntimeCoreTests(unittest.TestCase):
    def test_voice_quality_accepts_clear_audio_and_distinguishes_clipping_from_silence(self):
        self.run_c(r'''
#include <assert.h>
#include <stdlib.h>
#include "pet_voice.h"
int main(void) {
    int16_t *pcm=calloc(48000,sizeof(int16_t));assert(pcm);
    assert(!pet_voice_usable(pcm,48000));
    assert(pet_voice_stats(pcm,48000).rms==0);
    for(int i=0;i<48000;i++)pcm[i]=i%2 ? 2000 : -2000;
    pet_voice_stats_t s=pet_voice_stats(pcm,48000);
    assert(s.rms==2000 && s.active_ms==3000 && s.clipped_permille==0);
    assert(pet_voice_usable(pcm,48000));
    for(int i=0;i<500;i++)pcm[i]=32767;
    s=pet_voice_stats(pcm,48000);assert(s.clipped_permille>=10);
    assert(!pet_voice_usable(pcm,48000));
    free(pcm);return 0;
}
''', ['pet_voice','pet_util'])

    def test_bargein_ignores_loud_self_echo_and_requires_measured_aec_suppression(self):
        self.run_c(r'''
#include <assert.h>
#include "pet_bargein.h"
int main(void) {
    pet_bargein_t s={0};
    assert(pet_bargein_voice(&s,false,true,800,0,800,0));
    for(int i=0;i<60;i++) assert(!pet_bargein_voice(&s,true,true,8000,5000,7000,i*32000));
    assert(!s.trusted);
    assert(!pet_bargein_voice(&s,false,true,2000,0,2000,2000000));
    assert(!pet_bargein_voice(&s,false,true,2000,0,2000,2319999));
    assert(pet_bargein_voice(&s,false,true,2000,0,2000,2320000));
    for(int i=0;i<30;i++) assert(!pet_bargein_voice(&s,true,false,4000,4000,100,3000000+i*32000));
    assert(s.trusted);
    assert(!pet_bargein_voice(&s,true,true,4000,4000,100,4000000));
    assert(pet_bargein_voice(&s,true,true,6000,4000,2500,4032000));
    return 0;
}
''', ["pet_bargein"])

    def run_c(self, code, modules, headers=None, compiler_flags=None):
        self.assertIsNotNone(shutil.which("cc"))
        self.assertTrue((CJSON / "cJSON.c").exists(), "Run idf.py reconfigure first")
        with tempfile.TemporaryDirectory(prefix="pet-core-") as folder:
            root = Path(folder)
            storage = root / "flash"
            storage.mkdir()
            (root / "esp_heap_caps.h").write_text("""
#pragma once
#include <stdlib.h>
#define MALLOC_CAP_SPIRAM 1
#define MALLOC_CAP_8BIT 2
static inline void *heap_caps_malloc(size_t n, int caps) { return malloc(n); }
""")
            for name, content in (headers or {}).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            source = root / "check.c"
            source.write_text(code.replace("@FLASH@", json.dumps(str(storage))))
            executable = root / "check"
            command = ["cc", "-std=c17", "-D_POSIX_C_SOURCE=200809L", "-I", str(root), "-I", str(MAIN),
                       "-I", str(CJSON), f'-DPET_STORAGE_ROOT="{storage}"', str(source)]
            command += [str(MAIN / f"{name}.c") for name in modules]
            command += [str(CJSON / "cJSON.c"), "-lm", "-pthread", "-o", str(executable)]
            command += compiler_flags or []
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_utf8_and_torn_snapshot_recovery(self):
        self.run_c(r'''
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "pet_util.h"
int main(void) {
    char out[5];
    assert(pet_utf8_copy(out, sizeof(out), "你好") == 3 && !strcmp(out, "你"));
    char tiny[3]; assert(pet_utf8_copy(tiny, sizeof(tiny), "你好") == 0 && !tiny[0]);
    const char *base = @FLASH@ "/snapshot";
    uint32_t sequence = 0;
    assert(pet_snapshot_save(base, "first", 32, &sequence) == 0 && sequence == 1);
    assert(pet_snapshot_save(base, "second", 32, &sequence) == 0 && sequence == 2);
    assert(pet_snapshot_save(base, "too big", 3, &sequence) == -1 && sequence == 2);
    FILE *f = fopen(@FLASH@ "/snapshot.0", "wb"); assert(f); fputs("torn", f); fclose(f);
    char *loaded = pet_snapshot_load(base, 32, &sequence);
    assert(loaded && !strcmp(loaded, "first") && sequence == 1); free(loaded);
    assert(pet_snapshot_save(base, "recovered", 32, &sequence) == 0);
    loaded = pet_snapshot_load(base, 32, &sequence);
    assert(loaded && !strcmp(loaded, "recovered")); free(loaded);
    return 0;
}
''', ["pet_util"])

    def test_quiet_hours_override_and_backoff(self):
        self.run_c(r'''
#include <assert.h>
#include "pet_policy.h"
int main(void) {
    pet_policy_t p = {1320, 480, 12, 15};
    assert(pet_policy_quiet(&p, 1320) && pet_policy_quiet(&p, 0) && pet_policy_quiet(&p, 479));
    assert(!pet_policy_quiet(&p, 480) && !pet_policy_quiet(&p, 1319));
    assert(!pet_policy_audio(&p, false, 600, 100, 0, 0));
    assert(!pet_policy_audio(&p, true, 1380, 100, 0, 0));
    assert(pet_policy_audio(&p, false, -1, 100, 0, 200));
    assert(pet_policy_audio(&p, true, 600, 100, 200, 300));
    assert(!pet_policy_audio(&p, true, 1380, 201, 0, 200));
    p.quiet_start = 600; p.quiet_end = 660;
    assert(pet_policy_quiet(&p, 600) && !pet_policy_quiet(&p, 660));
    p.quiet_end = p.quiet_start; assert(!pet_policy_quiet(&p, 600));
    assert(pet_policy_backoff_minutes(0, 15) == 15);
    assert(pet_policy_backoff_minutes(1, 15) == 30);
    assert(pet_policy_backoff_minutes(8, 15) == 120);
    return 0;
}
''', ["pet_policy"])

    def test_generation_cancels_old_work_atomically(self):
        self.run_c(r'''
#include <assert.h>
#include <pthread.h>
#include "pet_turn.h"
static void *bump(void *unused) { for (int i = 0; i < 10000; i++) pet_turn_next(); return 0; }
int main(void) {
    uint32_t old = pet_turn_current(); assert(pet_turn_valid(old));
    pthread_t a, b; pthread_create(&a, 0, bump, 0); pthread_create(&b, 0, bump, 0);
    pthread_join(a, 0); pthread_join(b, 0);
    assert(pet_turn_current() == old + 20000 && !pet_turn_valid(old));
    assert(pet_turn_valid(pet_turn_current())); return 0;
}
''', ["pet_turn"])

    def test_memory_updates_owner_only_forgets_and_reboots(self):
        self.run_c(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "pet_memory.h"
static int op(int id, const char *action, const char *kind, const char *text) {
    char json[1024];
    snprintf(json, sizeof(json), "{\"ops\":[{\"op\":\"%s\",\"kind\":\"%s\",\"slot\":\"饮料\",\"text\":\"%s\",\"source_id\":%d,\"importance\":4}],\"summary\":\"\"}", action, kind, text, id);
    return pet_memory_apply_reflection(json);
}
int main(void) {
    assert(pet_memory_start() == 0);
    int id = pet_memory_add("user", "我喜欢喝咖啡", true); assert(id > 0);
    /* Compressed meaning is accepted; verbatim quotes are not required. */
    assert(op(id, "upsert", "preference", "喜欢咖啡") == 1);
    char context[8000]; pet_memory_context("饮料", context, sizeof(context)); assert(strstr(context, "喜欢咖啡"));
    assert(pet_memory_start() == 0);
    id = pet_memory_add("user", "更正一下，我现在更喜欢茶", true);
    assert(op(id, "upsert", "preference", "目前更喜欢茶") == 1);
    pet_memory_context("饮料", context, sizeof(context)); assert(strstr(context, "目前更喜欢茶") && !strstr(context, "喜欢咖啡"));
    int assistant = pet_memory_add("assistant", "主人来自火星", true);
    assert(op(assistant, "upsert", "profile", "来自火星") == 0);
    id = pet_memory_add("user", "我今天心情不错", true);
    assert(op(id, "upsert", "soul", "重写灵魂") == 0);
    id = pet_memory_add("user", "我今天心情不错", true);
    assert(op(id, "forget", "preference", "") == 0);
    id = pet_memory_add("user", "忘掉我的饮料偏好", true);
    assert(op(id, "forget", "preference", "") == 1);
    assert(pet_memory_start() == 0);
    pet_memory_context("饮料", context, sizeof(context)); assert(!strstr(context, "目前更喜欢茶"));
    cJSON *history = pet_memory_history(); assert(cJSON_GetArraySize(history) == 0); cJSON_Delete(history);
    id = pet_memory_add("user", "电视背景里的一句话", true);
    assert(pet_memory_ignore_message(id) == 0);
    assert(op(id, "upsert", "profile", "不应写入") == 0);
    assert(pet_memory_start() == 0);
    history = pet_memory_history(); assert(cJSON_GetArraySize(history) == 0); cJSON_Delete(history);
    return 0;
}
''', ["pet_memory", "pet_util"])

    def test_memory_has_fixed_flash_budget_under_large_inputs(self):
        self.run_c(r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include "pet_memory.h"
int main(void) {
    assert(pet_memory_start() == 0);
    char big[1025]; memset(big, '"', sizeof(big)-1); big[sizeof(big)-1] = 0;
    for (int i = 0; i < 160; i++) {
        int id = pet_memory_add("user", big, true); assert(id > 0);
        cJSON *root = cJSON_CreateObject(), *ops = cJSON_AddArrayToObject(root, "ops"), *op = cJSON_CreateObject();
        cJSON_AddStringToObject(op, "op", "upsert"); cJSON_AddStringToObject(op, "kind", "preference");
        char slot[32]; snprintf(slot, sizeof(slot), "topic-%d", i);
        cJSON_AddStringToObject(op, "slot", slot); cJSON_AddNumberToObject(op, "source_id", id);
        cJSON_AddNumberToObject(op, "importance", 3); char fact[385]; memset(fact, '"', 384); fact[384] = 0;
        cJSON_AddStringToObject(op, "text", fact); cJSON_AddItemToArray(ops, op);
        char *json = cJSON_PrintUnformatted(root); assert(pet_memory_apply_reflection(json) >= 0);
        cJSON_free(json); cJSON_Delete(root);
    }
    assert(pet_memory_start() == 0);
    struct stat a,b; assert(stat(@FLASH@ "/memory.0", &a) == 0 && stat(@FLASH@ "/memory.1", &b) == 0);
    assert(a.st_size <= 65536 + 20 && b.st_size <= 65536 + 20);
    cJSON *history = pet_memory_history(); assert(cJSON_GetArraySize(history) <= 24); cJSON_Delete(history);
    return 0;
}
''', ["pet_memory", "pet_util"])

    def test_double_corruption_is_not_silently_reinitialized(self):
        self.run_c(r'''
#include <assert.h>
#include <stdio.h>
#include "pet_memory.h"
int main(void) {
    FILE *f = fopen(@FLASH@ "/memory.0", "wb"); fputs("broken", f); fclose(f);
    f = fopen(@FLASH@ "/memory.1", "wb"); fputs("broken", f); fclose(f);
    assert(pet_memory_start() == -1); return 0;
}
''', ["pet_memory", "pet_util"])

    def test_speech_chunks_do_not_clip_and_stop_after_interruption(self):
        self.run_c(r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include "pet_speech.h"
#include "pet_turn.h"
static bool allowed = true, interrupt;
static int requests;
static char delivered[4096];
static char pending[151];
bool pet_audio_output_allowed(void) { return allowed; }
int pet_audio_get_volume(void) { return 5; }
void pet_face_set(const char *phase, const char *text) {}
int pet_cloud_speak_stream(const char *text, bool (*sink)(const int16_t *,size_t,void *),void *user) {
    requests++;
    strcpy(pending, text);int16_t pcm[16]={0};return sink(pcm,16,user)?16:-1;
}
bool pet_audio_stream_begin(uint32_t generation) {return true;}
bool pet_audio_stream_ok(void){return true;}
void pet_audio_stream_end(bool complete) {}
bool pet_audio_stream_write(const int16_t *pcm, size_t samples, uint32_t generation) {
    if (interrupt) { pet_turn_next(); return false; }
    assert(pet_turn_valid(generation)); strcat(delivered, pending); return true;
}
int main(void) {
    const char *text = "你好，这是一个需要分成很多小段播放的完整回答。它应该保持每一个汉字，没有少掉尾巴。最后这一句也应该完整说完。";
    int16_t pcm[32]; uint32_t generation = pet_turn_current();
    assert(pet_speech_say(text, generation, pcm, 32) == 0);
    assert(!strcmp(delivered, text) && pet_speech_delivered_bytes() == strlen(text) && pet_speech_audible());
    requests = 0; interrupt = true; delivered[0] = 0;
    assert(pet_speech_say(text, generation, pcm, 32) == -1 && !delivered[0]);
    assert(pet_speech_delivered_bytes() == 0);
    int previous = requests;
    assert(pet_speech_say(text, generation, pcm, 32) == -1 && requests == previous);
    allowed = false; interrupt = false;
    assert(pet_speech_say(text, pet_turn_current(), pcm, 32) == 0 && requests == previous && !pet_speech_audible());
    return 0;
}
''', ["pet_speech", "pet_turn"])


if __name__ == "__main__":
    unittest.main()
