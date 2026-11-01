/* GPL-2.0-only. Experimental GR III 2.10 native launcher.
 * Fixed addresses are accepted only by the exact-image guards in pack.mjs.
 * Timer/cache/heap execution still require testing on a physical camera.
 */
#include "runtime-offsets.h"
typedef unsigned int u32;
typedef unsigned char u8;
extern const u8 doom_image[], doom_wad[];
extern const u32 doom_fixups[];
#define OWNER (*(void *volatile *)0x5580438cu)
#define MAGIC 0x4d4f4f44u
#define CONTROLLER_VT 0x53b2f9e8u
#define ARENA_BYTES (8u * 1024u * 1024u)
#define STACK_BYTES (128u * 1024u)
typedef struct {
    u32 vtable, controller, timer, armed;
    u32 vt[4];
    u32 magic, active, busy, owned, runtime, stack, arena;
} Session;
static u32 word(const void *p, u32 off) { return *(const u32 *)((const u8 *)p + off); }
static void put(void *p, u32 off, u32 v) { *(u32 *)((u8 *)p + off) = v; }
static int ptr(u32 p) { return p >= 0x40000000u && p < 0xc0000000u && !(p & 3); }
static void *owner(void) {
    void *c = OWNER;
    return ptr((u32)c) && word(c, 0) == CONTROLLER_VT && word(c, 0x6a0) == MAGIC ? c : 0;
}
static Session *session(void *c) {
    Session *s = (Session *)word(c, 0x6a4);
    return ptr((u32)s) && s->magic == ((u32)s ^ MAGIC) && s->controller == (u32)c ? s : 0;
}
static void *timers(void) {
    void *factory = ((void *(*)(void))0x5320ad88)();
    return ((void *(*)(void *))0x5320b01c)(factory);
}
static int shooting(void) {
    void *factory = ((void *(*)(void))0x5320ad88)();
    void *manager = ((void *(*)(void *))0x5320aefc)(factory);
    u32 id = ((u32 (*)(void *))0x53228c4c)(manager);
    return id >= 0x08000000u && id <= 0x08000002u;
}
static void dirty(void *c) {
    ((u8 *)c)[0x14e] = 1;
    void *root = (void *)word(c, 0x15c);
    if (ptr((u32)root)) ((void (*)(void *))0x533ab98c)(root);
}
/* Call game code on a private stack. Camera task stacks are not sized for DOOM.
 * Six input arguments: the last two are on the original stack at +24/+28. */
__attribute__((naked)) u32 camera_call(u32 top __attribute__((unused)), u32 entry __attribute__((unused)),
    u32 a __attribute__((unused)), u32 b __attribute__((unused)), u32 c __attribute__((unused)), u32 d __attribute__((unused))) {
    __asm__ volatile("push {r4-r6,lr}\nmov r4,sp\nmov r6,r0\nmov r5,r1\nmov r0,r2\nmov r1,r3\n"
                     "ldr r2,[r4,#16]\nldr r3,[r4,#20]\nmov sp,r6\nblx r5\nmov sp,r4\npop {r4-r6,pc}");
}
static u32 run(Session *s, u32 offset, u32 a, u32 b, u32 c, u32 d) {
    return camera_call(s->stack, s->runtime + offset, a, b, c, d);
}
static void cancel(Session *s) {
    if (s->armed) ((void (*)(void *, u32))0x5322b1ec)(timers(), s->timer);
    s->armed = 0;
}
static void close_game(void *c, Session *s) {
    s->active = 0; cancel(s);
    run(s, OFFSET_gr3_release_keys, 0, 0, 0, 0);
    dirty(c);
}
static void arm(Session *s) {
    s->armed = 1;
    /* 29 is a nominal 35 Hz interval if the service uses milliseconds. Actual
     * cadence and callback task context are expressly hardware-unverified. */
    s->timer = ((u32 (*)(void *, u32, void *))0x5322b468)(timers(), 29, s);
}
void camera_tick(Session *s) {
    if (!ptr((u32)s) || s->magic != ((u32)s ^ MAGIC)) return;
    s->armed = 0;
    void *c = owner();
    if (!c || s->controller != (u32)c || !s->active) return;
    if (s->busy) { arm(s); return; }
    if (!shooting()) { close_game(c, s); return; }
    s->busy = 1;
    u32 success = run(s, OFFSET_gr3_tick, 0, 0, 0, 0);
    s->busy = 0;
    if (!success) { close_game(c, s); return; }
    dirty(c); arm(s);
}
static void sync_code(u32 address, u32 size) {
    /* ARMv7 clean-to-PoU + I-cache invalidate + barriers. These instructions
     * require a privileged RTOS task and executable heap mappings. */
    u32 ctr, zero = 0;
    __asm__ volatile("mrc p15,0,%0,c0,c0,1" : "=r"(ctr));
    u32 line = 4u << ((ctr >> 16) & 15u);
    for (u32 at = address & ~(line - 1u); at < address + size; at += line)
        __asm__ volatile("mcr p15,0,%0,c7,c11,1" :: "r"(at) : "memory");
    __asm__ volatile("dsb\nmcr p15,0,%0,c7,c5,0\ndsb\nisb" :: "r"(zero) : "memory");
}
static Session *create_session(void *c) {
    u32 bytes = sizeof(Session) + 32u + DOOM_IMAGE_BYTES + ARENA_BYTES + STACK_BYTES;
    Session *s = ((Session *(*)(u32))0x536af31c)(bytes);
    if (!ptr((u32)s)) return 0;
    u8 *raw = (u8 *)s;
    for (u32 i = 0; i < sizeof(Session); ++i) raw[i] = 0;
    s->vtable = (u32)&s->vt[0]; s->controller = (u32)c;
    for (u32 i = 0; i < 4; ++i) s->vt[i] = (u32)&camera_tick;
    s->magic = (u32)s ^ MAGIC;
    s->runtime = ((u32)s + sizeof(Session) + 15u) & ~15u;
    s->arena = s->runtime + DOOM_IMAGE_BYTES;
    s->stack = s->arena + ARENA_BYTES + STACK_BYTES;
    for (u32 i = 0; i < DOOM_IMAGE_BYTES; ++i) ((u8 *)s->runtime)[i] = doom_image[i];
    for (u32 i = 0; i < DOOM_FIXUP_COUNT; ++i) {
        u32 *p = (u32 *)(s->runtime + doom_fixups[i]); *p += s->runtime;
    }
    sync_code(s->runtime, DOOM_IMAGE_BYTES);
    if (!run(s, OFFSET_gr3_init, s->arena, ARENA_BYTES, (u32)doom_wad, DOOM_WAD_BYTES)) {
        ((void (*)(void *))0x536af358)(s); return 0;
    }
    put(c, 0x6a4, (u32)s);
    return s;
}
u32 camera_try_open(void) {
    void *c = owner();
    if (!c || !shooting()) return 0;
    Session *s = session(c);
    if (!s) s = create_session(c);
    if (!s || s->busy) return 0;
    if (s->active) { close_game(c, s); return 1; }
    s->owned |= 1u << 27;  /* launch Fn press belongs to us through release */
    s->active = 1; dirty(c); arm(s); return 1;
}
u32 camera_construct(void *c) {
    u32 result = ((u32 (*)(void *))0x53173204)(c);
    for (u32 off = 0x69c; off < 0x6c0; off += 4) put(c, off, 0);
    put(c, 0x6a0, MAGIC); OWNER = c;
    return result;
}
void camera_cleanup(void *c) {
    if (OWNER != c) return;
    Session *s = session(c);
    if (s) {
        cancel(s); s->active = 0; s->magic = 0;
        ((void (*)(void *))0x536af358)(s);
    }
    put(c, 0x6a4, 0); OWNER = 0;
}
__attribute__((naked)) void camera_destroy(void *c __attribute__((unused))) {
    __asm__ volatile("push {r0-r3,r4,lr}\nbl camera_cleanup\npop {r0-r3,r4,lr}\nmov ip,sp\nldr pc,1f\n1: .word 0x53170b54");
}
u32 camera_draw(void *root) {
    u32 result = ((u32 (*)(void *))0x53391b14)(root);
    void *c = owner();
    if (!c || word(c, 0x15c) != (u32)root) return result;
    Session *s = session(c);
    if (!s || !s->active || s->busy) return result;
    s->busy = 1;
    run(s, OFFSET_gr3_blit, word(root, 0xec), 0, 0, 0);
    s->busy = 0; return result;
}
__attribute__((naked)) void camera_open(void) {
    __asm__ volatile("push {r0-r3,r4,lr}\nbl camera_try_open\ncmp r0,#0\npop {r0-r3,r4,lr}\n"
                     "bxne lr\nmov ip,sp\nldr pc,1f\n1: .word 0x53227118");
}
u32 camera_filter(void *message) {
    void *c = owner(); if (!c || !ptr((u32)message)) return 0;
    Session *s = session(c); if (!s || s->busy) return 0;
    u32 id = *(const unsigned short *)message;
    void *payload = (void *)word(message, 4);
    if (!ptr((u32)payload)) return 0;
    u32 phase = *(const u8 *)payload;
    u32 mask = id < 32 ? 1u << id : 0;
    if (phase == 2 && (s->owned & mask)) {
        s->owned &= ~mask;
        if (s->active) run(s, OFFSET_gr3_key, id, 0, 0, 0);
        return 1;
    }
    if (!s->active) return (s->owned & mask) != 0;  /* suppress held repeats until release */
    if (id == 1 || id == 2 || id == 3 || id == 5 || id == 20 || id == 23 ||
        id == 24 || id == 26 || id == 32 || id == 38) { close_game(c, s); return 0; }
    if (id != 4 && id != 8 && id != 9 && id != 10 && id != 11 && id != 12 && id != 27 && id != 30) return 0;
    if (phase == 1) {
        s->owned |= mask; run(s, OFFSET_gr3_key, id, 1, 0, 0);
    }
    return 1;
}
__attribute__((naked)) u32 camera_event(void *action __attribute__((unused)), void *message __attribute__((unused))) {
    __asm__ volatile("push {r0-r3,r4,lr}\nmov r0,r1\nbl camera_filter\ncmp r0,#0\npop {r0-r3,r4,lr}\n"
                     "movne r0,#1\nbxne lr\nldrh r3,[r1]\nldr pc,1f\n1: .word 0x532231e8");
}
