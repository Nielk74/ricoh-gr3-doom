"""Exercise the packaged native hooks plus actual ARM DOOM with RTOS services stubbed.

This is a function probe, not a camera boot/display/scheduler emulator.
"""
import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path
from PIL import Image
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_PROT_READ, UC_PROT_EXEC
from unicorn import arm_const as reg
from verify import Runtime, DESC, PIXELS

CONTROLLER, ROOT, MESSAGE, PAYLOAD = 0x62010000, 0x62020000, 0x62030000, 0x62030100
HEAP, OWNER = 0x68000000, 0x5580438c


class CameraProbe(Runtime):
    def __init__(self, runtime, candidate):
        self.runtime_manifest = json.loads((runtime / 'runtime.json').read_text(encoding='utf-8'))
        self.candidate_manifest = json.loads((candidate / 'candidate.json').read_text(encoding='utf-8'))
        self.rom = (candidate / 'rtos.bin').read_bytes()
        assert hashlib.sha256((candidate / 'candidate.bin').read_bytes()).hexdigest() == self.candidate_manifest['outputSha256']
        decoded = subprocess.run(['node', '--experimental-transform-types', str(Path(__file__).with_name('inspect.mjs')),
                                  str(candidate / 'candidate.bin'), str(candidate / 'rtos.bin')],
                                 capture_output=True, text=True, encoding='utf-8', check=True)
        self.decoded = json.loads(decoded.stdout)
        assert self.decoded['candidateSha256'] == self.candidate_manifest['outputSha256']
        assert self.candidate_manifest['module']['runtimeSha256'] == self.runtime_manifest['imageSha256']
        for asset in self.candidate_manifest['module']['assets'].values():
            start = asset['address'] - 0x53000000
            assert hashlib.sha256(self.rom[start:start + asset['bytes']]).hexdigest() == asset['sha256']
        assert self.candidate_manifest['module']['assets']['doom_image']['sha256'] == self.runtime_manifest['imageSha256']
        self.base = 0
        self.manifest = dict(exports=self.candidate_manifest['module']['exports'].copy())
        self.manifest['exports'].update(native_open=0x53227114, native_event=0x532231e4, native_destroy=0x53170b50)
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.uc.ctl_set_cpu_model(reg.UC_CPU_ARM_CORTEX_A9)
        self.uc.mem_map(0x53000000, (len(self.rom) + 4095) & ~4095)
        self.uc.mem_write(0x53000000, self.rom)
        self.uc.mem_protect(0x53000000, (len(self.rom) + 4095) & ~4095, UC_PROT_READ | UC_PROT_EXEC)
        for address, length in [(0x61000000, 0x100000), (0x62000000, 0x100000), (DESC, 0x200000),
                                (HEAP, 0x1000000), (OWNER & ~4095, 4096)]: self.uc.mem_map(address, length)
        self.uc.reg_write(reg.UC_ARM_REG_C1_C0_2, 0xf00000)
        self.uc.reg_write(reg.UC_ARM_REG_FPEXC, 0x40000000)
        self.events, self.pending, self.serial, self.alloc_fail = [], None, 0, False
        self.mode = 0x08000000
        # Hook only service entry addresses: no per-instruction Python callback
        # in the game. No DOOM functions, WAD reads or pixel stores are stubbed.
        services = [0x53173204, 0x5320ad88, 0x5320b01c, 0x5320aefc, 0x53228c4c,
                    0x536af31c, 0x536af358, 0x5322b468, 0x5322b1ec, 0x533ab98c,
                    0x53391b14, 0x532231e8, 0x53227118, 0x53170b54]
        for at in services: self.uc.hook_add(UC_HOOK_CODE, self.service, begin=at, end=at)
        self.put(CONTROLLER, 0, 0x53b2f9e8)
        self.put(CONTROLLER, 0x15c, ROOT)
        self.put(ROOT, 0, 0x53c09f10); self.put(ROOT, 0xec, DESC)
        descriptor = bytearray(0x28); descriptor[2] = 5
        struct.pack_into('<I', descriptor, 8, PIXELS)
        struct.pack_into('<4H', descriptor, 0x18, 736, 480, 720, 480)
        self.uc.mem_write(DESC, bytes(descriptor))

    def put(self, p, off, value): self.uc.mem_write(p + off, struct.pack('<I', value))
    def word(self, p, off=0): return struct.unpack('<I', self.uc.mem_read(p + off, 4))[0]

    def service(self, cpu, at, size, user):
        args = [cpu.reg_read(getattr(reg, f'UC_ARM_REG_R{i}')) for i in range(4)]
        result = 0
        if at == 0x53173204: result = args[0]
        elif at in (0x5320ad88, 0x5320b01c, 0x5320aefc): result = 0x62050000
        elif at == 0x53228c4c: result = self.mode
        elif at == 0x536af31c:
            assert args[0] < 0x1000000
            self.events.append(('allocate', args[0])); result = 0 if self.alloc_fail else HEAP
        elif at == 0x536af358: self.events.append(('free', args[0]))
        elif at == 0x5322b468:
            assert self.pending is None, 'Two game timers are pending'
            self.serial += 1; result = self.serial; self.pending = (result, args[2])
            self.events.append(('arm', args[1]))
        elif at == 0x5322b1ec:
            assert self.pending and self.pending[0] == args[1]
            self.pending = None; self.events.append(('cancel', args[1]))
        elif at == 0x533ab98c: self.events.append(('invalidate', args[0]))
        elif at == 0x53391b14: self.events.append(('nativeCanvas', args[0])); result = 0x1234
        elif at == 0x532231e8:
            assert args[3] == self.word(args[1]) & 0xffff, 'Displaced LDRH not replayed'
            self.events.append(('nativeEvent', args[3])); result = 0xbeef
        elif at == 0x53227118: self.events.append(('nativeFn',)); result = 0xbeef
        elif at == 0x53170b54: self.events.append(('nativeDestroy', args[0]))
        cpu.reg_write(reg.UC_ARM_REG_R0, result)
        cpu.reg_write(reg.UC_ARM_REG_PC, cpu.reg_read(reg.UC_ARM_REG_LR))

    def launch(self):
        assert self.call('camera_construct', CONTROLLER) == CONTROLLER
        assert self.word(OWNER) == CONTROLLER
        self.call('native_open')
        assert self.pending
        self.s = self.word(CONTROLLER, 0x6a4)
        runtime_base = self.word(self.s, 48)
        for name, offset in self.runtime_manifest['exports'].items(): self.manifest['exports'][name] = runtime_base + offset
        self.event(27, 2)  # consume launch Fn release

    def timer(self, count=1):
        for _ in range(count):
            assert self.pending
            _, listener = self.pending; self.pending = None
            callback = self.word(self.word(listener), 8)
            assert callback == self.manifest['exports']['camera_tick']
            self.manifest['exports']['listener_tick'] = callback
            self.call('listener_tick', listener)

    def event(self, key, phase):
        self.put(MESSAGE, 0, key); self.put(MESSAGE, 4, PAYLOAD)
        self.uc.mem_write(PAYLOAD, bytes([phase]))
        return self.call('native_event', 0x62040000, MESSAGE)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('runtime', type=Path); ap.add_argument('candidate', type=Path)
    a = ap.parse_args(); p = CameraProbe(a.runtime, a.candidate); p.launch(); p.timer(4)
    assert p.word(0x53c0a504) == 30  # original SwitchTestView identity
    label = p.word(0x53c0a508)
    assert bytes(p.uc.mem_read(label, 6)) == b'ADJ-P\0'
    assert p.call('gr3_status', 0) == 1
    before = len(p.events)
    assert p.call('camera_draw', ROOT) == 0x1234
    assert p.events[before] == ('nativeCanvas', ROOT)
    framebuffer = bytes(p.uc.mem_read(PIXELS, 736 * 480 * 4))
    visible = b''.join(framebuffer[y * 736 * 4:(y * 736 + 720) * 4] for y in range(480))
    assert visible == Image.open(a.runtime / 'doom-title.png').convert('RGBA').tobytes(), 'Packaged title differs from the verified engine'
    # Even a foreign canvas sharing the same descriptor must not receive DOOM.
    foreign = ROOT + 0x1000
    p.put(foreign, 0xec, DESC)
    sentinel = b'\xa5' * len(framebuffer)
    p.uc.mem_write(PIXELS, sentinel)
    assert p.call('camera_draw', foreign) == 0x1234
    assert bytes(p.uc.mem_read(PIXELS, len(sentinel))) == sentinel, 'Foreign canvas received game pixels'
    for _ in range(4):
        assert p.event(30, 1) == 1; p.timer(2)
        assert p.event(30, 2) == 1; p.timer(2)
    p.timer(70)
    assert p.call('gr3_status', 5) == 0 and p.call('gr3_status', 6) == 0
    position = (p.call('gr3_status', 7), p.call('gr3_status', 8))
    assert p.event(9, 1) == 1; p.timer(16)
    assert (p.call('gr3_status', 7), p.call('gr3_status', 8)) != position
    assert p.event(30, 1) == 1
    assert ('nativeEvent', 30) not in p.events, 'ADJ press reached native camera while game active'
    assert p.event(5, 1) == 0xbeef  # MENU closes and reaches native camera
    assert p.pending is None and p.call('gr3_status', 4) == 0
    p.uc.mem_write(PIXELS, sentinel)
    assert p.call('camera_draw', ROOT) == 0x1234
    assert bytes(p.uc.mem_read(PIXELS, len(sentinel))) == sentinel, 'DOOM or watermark remained after exit'
    assert p.event(9, 1) == 1  # repeats remain owned after exit, before release
    assert p.event(9, 2) == 1  # consume the held movement key's release after exit
    assert p.event(9, 1) == 0xbeef  # ordinary native input after exit
    assert p.event(30, 1) == 1  # held ADJ repeat stays owned through exit
    assert p.event(30, 2) == 1
    assert p.event(30, 1) == 0xbeef  # ordinary ADJ works outside DOOM
    p.call('native_open'); p.event(27, 2)
    assert len([e for e in p.events if e[0] == 'allocate']) == 1, 'Resume leaked a game runtime'
    p.put(p.s, 40, 1); p.timer()  # an overlapping presentation must not lose the timer
    assert p.pending and p.call('gr3_status', 0) == 1
    p.put(p.s, 40, 0); p.timer()
    p.mode = 0x01000000; p.timer()
    assert p.pending is None and p.call('gr3_status', 4) == 0
    p.mode = 0x08000000; p.call('native_open'); p.event(27, 2)
    p.call('native_destroy', CONTROLLER)
    assert p.pending is None and p.word(OWNER) == 0
    assert ('free', HEAP) in p.events
    assert bytes(p.uc.mem_read(0x53000000, len(p.rom))) == p.rom, 'Firmware code/assets were modified at runtime'
    failed = CameraProbe(a.runtime, a.candidate); failed.alloc_fail = True
    failed.call('camera_construct', CONTROLLER)
    assert failed.call('native_open') == 0xbeef and failed.pending is None
    report = dict(schema=1, candidateSha256=p.candidate_manifest['outputSha256'],
                  actualPackagedHooksExecuted=True, actualArmGameExecuted=True,
                  nativeTimerListenerExecuted=True, realMapEntered=True, playerMoved=True,
                  foreignCanvasUntouched=True, exitedCanvasUntouched=True,
                  privateStackAndAapcsVerified=True, nativeCanvasPrecedesGameBlit=True,
                  menuExitAndHeldReleaseVerified=True, heldRepeatsAfterExitVerified=True,
                  busyTimerRecoveryVerified=True, modeExitVerified=True,
                  resumeReusesAllocation=True, allocationFailureFallsThrough=True,
                  destructorCancelsTimerAndFrees=True, romUnmodified=True, hardwareTested=False,
                  decodedCandidateMatchesExecutedRtos=True, embeddedAssetsMatchVerifiedInputs=True,
                  adjPressNativeIdentityVerified=True, adjPressConfirmWithoutOkVerified=True,
                  adjPressOwnershipAndNativeFallbackVerified=True,
                  rtosSha256=p.decoded['rtosSha256'],
                  substitutions=['Native controller initialiser', 'Application factory and current-mode query',
                                 'Allocator/free', 'Timer register/cancel and callback delivery',
                                 'Canvas draw/invalidation', 'Native dispatcher/Fn/destructor continuation'],
                  limits=['No full boot or physical flash', 'No real scheduler/task concurrency',
                          'No real cache/MMU/LCD/DMA', 'No physical input or memory-pressure measurement'])
    (a.candidate / 'camera-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
