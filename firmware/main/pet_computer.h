#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
int pet_computer_start(void);
/* Read-only authenticated health check; never submits or resumes a task. */
void pet_computer_check_connection(uint32_t now);
/* Client id supplied once from hardware RNG, then checkpointed before HTTP. */
int pet_computer_submit(const char *goal,const char *client_id);
int pet_computer_queue(const char *goal);
int pet_computer_cancel(void);
/* Explicit continuation creates a new durable request ID; never replays old work. */
int pet_computer_resume(const char *parent_id);
int pet_computer_resume_id(const char *parent_id,const char *new_id);
void pet_computer_tick(uint32_t now,bool interactive);
void pet_computer_context(char *out,size_t capacity);
/* Durable terminal notices: peek is inert; acknowledge only after delivery. */
bool pet_computer_result_pending(char *out,size_t capacity,char *receipt,size_t receipt_capacity);
int pet_computer_result_delivered(const char *receipt);
int pet_computer_result_announced(const char *receipt);
const char *pet_computer_current_id(void);
bool pet_computer_result_media(char *job_id,size_t capacity);
bool pet_computer_media_presented(const char *job_id);
const char *pet_computer_rules(void);
