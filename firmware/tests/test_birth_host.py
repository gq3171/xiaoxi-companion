"""Exercise actual semantic-state validation and staged identity output.

Model text is a controlled fixture here; real NLU is checked separately.
"""
import unittest
import test_runtime_core

class BirthHostTests(unittest.TestCase):
    def test_meaning_delegation_and_atomic_rejection(self):
        self.run_c(r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include "pet_birth.h"
int main(void){
 pet_birth_t b;pet_birth_init(&b);char q[384],summary[2600];
 char *request=pet_birth_request(&b,"以后你就叫做小西。",NULL);
 assert(strstr(request,"以后你就叫做小西"));free(request);
 assert(pet_birth_apply(&b,"{\"updates\":[{\"field\":\"name\",\"mode\":\"explicit\",\"value\":\"小西\"}],\"question\":\"我是什么样的桌宠？\"}",q,sizeof(q))==0);
 assert(!pet_birth_identity(&b));
 /* A late invalid operation cannot partially change an accepted name. */
 assert(pet_birth_apply(&b,"{\"updates\":[{\"field\":\"name\",\"mode\":\"explicit\",\"value\":\"乱改\"},{\"field\":\"api_key\",\"mode\":\"explicit\",\"value\":\"x\"}],\"question\":\"x\"}",q,sizeof(q))==-1);
 assert(!strcmp(cJSON_GetObjectItem(cJSON_GetObjectItem(b.fields,"name"),"value")->valuestring,"小西"));
 assert(pet_birth_apply(&b,"{\"updates\":[{\"field\":\"user_name\",\"mode\":\"develop\",\"value\":\"\"}],\"question\":\"x\"}",q,sizeof(q))==-1);
 assert(pet_birth_apply(&b,"{\"updates\":[],\"question\":\"\"}",q,sizeof(q))==-1);
 assert(pet_birth_apply(&b,"{\"updates\":[{\"field\":\"creature\",\"mode\":\"explicit\",\"value\":\"活泼可爱的桌宠\"},{\"field\":\"vibe\",\"mode\":\"explicit\",\"value\":\"活泼有趣，有自主性，愿意思考\"},{\"field\":\"soul\",\"mode\":\"develop\",\"value\":\"这个你自己定吧，我也不知道\"},{\"field\":\"user_name\",\"mode\":\"explicit\",\"value\":\"主人\"}],\"question\":\"\"}",q,sizeof(q))==1);
 cJSON *identity=pet_birth_identity(&b);assert(pet_birth_valid_identity(identity));
 pet_birth_summary(identity,summary,sizeof(summary));
 assert(strstr(summary,"名字：小西") && strstr(summary,"称呼你：主人"));
 assert(!strstr(summary,"不知道") && !strstr(summary,"自己定吧") && strstr(summary,"逐渐形成"));
 cJSON_ReplaceItemInObject(identity,"name",cJSON_CreateString(""));assert(!pet_birth_valid_identity(identity));
 cJSON_Delete(identity);pet_birth_free(&b);return 0;
}
''')

    def run_c(self, code):
        test_runtime_core.RuntimeCoreTests.run_c(self,code,['pet_birth','pet_util'])
