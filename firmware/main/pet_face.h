#pragma once
#include <stdbool.h>
#include <stdint.h>

void pet_face_start(void);
void pet_face_panel_refresh(void);
void pet_face_set(const char *phase, const char *text);
void pet_face_hint(const char *phase,const char *text);
/* Explicit accepted user request; optionally wait until actually lying down. */
void pet_face_screen_off(bool after_rest);
void pet_face_show_volume(int volume);
/* Physical left key: hold 1.2s to open/close. Safe from the buttons task. */
void pet_face_toggle_menu(void);
enum { PET_VOICE_PREVIEW=1, PET_VOICE_SAVE=2, PET_VOICE_CLOSE=3 };
bool pet_face_voice_open(void);
int pet_face_voice_wait(int *index, uint32_t *generation);
void pet_face_voice_status(const char *status);
void pet_face_voice_close(void);
void pet_face_identity(const char *creature);
int pet_face_input(const char *title, const char *hint, int secret, char *out, int capacity);
int pet_face_choose(const char *title, const char *options, char *out, int capacity);
int pet_face_confirm(const char *title, const char *text);
void pet_face_message(const char *text);
void pet_face_read(const char *text);
void pet_face_mood(const char *mood);
void pet_face_media_open(const char *title,bool playable);
bool pet_face_media_frame(const uint16_t *pixels,int width,int height);
void pet_face_media_status(const char *status,bool playing);
/* 1 play, 2 pause, 3 close, 4 back to list; consumed by runtime worker. */
int pet_face_media_control(void);
void pet_face_media_close(void);
/* 1..4 shows enrollment progress; 0 hides it. */
void pet_face_owner_recording(int sample);
void pet_face_owner_prompt(int sample, const char *phrase);
void pet_face_owner_end(void);

/* Show the explicit keyboard option during spoken birth questions. */
void pet_face_birth_input(int visible);

/* Cached UI permission for an unsolicited IMU reaction; no LVGL from worker. */
bool pet_face_motion_allowed(void);
bool pet_face_presentation_allowed(void);
void pet_face_result_pending(bool pending);
