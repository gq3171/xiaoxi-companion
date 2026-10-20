#pragma once
const char *pet_secrets_deepseek(void);
const char *pet_secrets_minimax(void);
void pet_secrets_start(void);
int pet_secrets_save(const char *deepseek, const char *minimax);
const char *pet_secrets_xfyun_appid(void);
const char *pet_secrets_xfyun_key(void);
const char *pet_secrets_xfyun_secret(void);
int pet_secrets_save_xfyun(const char *appid, const char *key, const char *secret);
