#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "pet_home.h"
typedef enum {
    PET_POSE_IDLE, PET_POSE_BLINK, PET_POSE_LISTEN, PET_POSE_THINK,
    PET_POSE_SPEAK, PET_POSE_HAPPY, PET_POSE_SLEEP, PET_POSE_TOUCH,
    PET_POSE_WALK_A, PET_POSE_WALK_B,
    PET_POSE_LIE_SLEEP, PET_POSE_WAKE, PET_POSE_WASH_A, PET_POSE_WASH_B,
    PET_POSE_WORK_A, PET_POSE_WORK_B, PET_POSE_WALK_BACK_A, PET_POSE_WALK_BACK_B,
    PET_POSE_COUNT
} pet_pose_t;
/* Extra drawing frames never enter the stable 34-word scene wire. */
typedef enum {
 PET_ART_SIDE_LEFT_0=PET_POSE_COUNT,PET_ART_SIDE_LEFT_1,PET_ART_SIDE_LEFT_2,PET_ART_SIDE_LEFT_3,
 PET_ART_SIDE_RIGHT_0,PET_ART_SIDE_RIGHT_1,PET_ART_SIDE_RIGHT_2,PET_ART_SIDE_RIGHT_3,
 PET_ART_BED_SIT,PET_ART_BED_STRETCH,PET_ART_STAND_STRETCH,PET_ART_STAND_RELAX,
 PET_ART_BACK_RIGHT_A,PET_ART_BACK_RIGHT_B,
 PET_ART_CAT_IDLE,PET_ART_CAT_WALK_A,PET_ART_CAT_WALK_B,PET_ART_CAT_SLEEP,
 PET_ART_CAT_WALK_C,PET_ART_CAT_WALK_D,PET_ART_CAT_BLINK,PET_ART_CAT_GROOM_A,PET_ART_CAT_GROOM_B,
 PET_ART_CAT_EAT_A,PET_ART_CAT_EAT_B,PET_ART_CAT_PET_A,PET_ART_CAT_PET_B,PET_ART_CAT_LIE_DOWN,PET_ART_CAT_WAKE,PET_ART_CAT_STRETCH,PET_ART_CAT_STAND,PET_ART_CAT_TURN,
 PET_ART_FRONT_PASS_A,PET_ART_FRONT_PASS_B,PET_ART_COUNT
} pet_art_t;
/* Mouth-open reaction reuses an existing frame; no extra bitmap storage. */
#define PET_POSE_SURPRISE PET_POSE_SPEAK
typedef struct {
    int x, y, target_x, target_y; /* Ground contact point, not bitmap top-left. */
    float precise_x, precise_y;
    uint32_t next_blink, blink_until, next_walk, reaction_until, last_engaged;
    uint32_t last_step, stage_started;
    bool replica; /* Local prediction never reports authoritative life completion. */
    bool dragging, pressed, moved, clock_seen, was_night, wake_wash, reading_requested, walk_backwards;
    int press_x, press_y, anchor_x, anchor_y, transition_x, transition_y;
    pet_pose_t pose, reaction;
    pet_home_activity_t activity;
    pet_place_t place, destination;
    pet_home_action_t after_wake;
    int route_x[3], route_y[3], route_length, route_index;
} pet_scene_t;
typedef struct {
    uint32_t now_ms, random, phase_ms;
    bool listening, thinking, speaking, blocked, night, tired, clock_valid, replica, phase_valid;
} pet_scene_input_t;
void pet_scene_init(pet_scene_t *scene, uint32_t now);
void pet_scene_step(pet_scene_t *scene, pet_scene_input_t in);
void pet_scene_command(pet_scene_t *scene, pet_home_action_t action, uint32_t now);
void pet_scene_projection(const pet_scene_t *scene, int *left, int *top, int *scale);
void pet_scene_press(pet_scene_t *scene, int x, int y, uint32_t now);
void pet_scene_drag(pet_scene_t *scene, int x, int y);
bool pet_scene_release(pet_scene_t *scene, uint32_t now);
void pet_scene_react(pet_scene_t *scene, pet_pose_t pose, uint32_t now);

unsigned pet_scene_art_frame(const pet_scene_t *scene,uint32_t now);

void pet_scene_walk_to(pet_scene_t *scene,int x,int y,uint32_t now);
