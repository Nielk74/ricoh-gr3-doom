"""Build a position-independent ARM DOOM runtime; no firmware or camera writes."""
import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENGINE_COMMIT = '355cfbd16fac119718879239336ee2ea408886bd'
ENGINE_SHA256 = 'ec16ce721436bf3fa4c338320afedd56a93c0b563a94ebf283718503c71ca780'


def relocate(raw, offsets, base):
    result = bytearray(raw)
    if len(offsets) != len(set(offsets)):
        raise ValueError('Duplicate relocation')
    for offset in offsets:
        if offset < 0 or offset % 4 or offset + 4 > len(raw):
            raise ValueError('Relocation outside image or unaligned')
        value = struct.unpack_from('<I', raw, offset)[0]
        if value >= len(raw):
            raise ValueError('Relocation target outside image')
        struct.pack_into('<I', result, offset, value + base)
    return bytes(result)


def validate_wad(raw):
    if len(raw) < 12 or raw[:4] != b'IWAD':
        raise ValueError('Expected a complete IWAD')
    count, directory = struct.unpack_from('<II', raw, 4)
    if not count or directory < 12 or directory + count * 16 > len(raw):
        raise ValueError('Invalid WAD directory')
    for i in range(count):
        start, size = struct.unpack_from('<II', raw, directory + i * 16)
        if start + size > len(raw):
            raise ValueError('Lump extends past WAD')


def main():
    from elftools.elf.elffile import ELFFile
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--engine', type=Path, required=True, help='Pinned PureDOOM.h')
    ap.add_argument('--wad', type=Path, required=True, help='User-supplied DOOM shareware IWAD')
    ap.add_argument('--out', type=Path, required=True)
    a = ap.parse_args()
    engine = a.engine.read_bytes()
    if hashlib.sha256(engine).hexdigest() != ENGINE_SHA256:
        raise ValueError('PureDOOM.h does not match the pinned source')
    wad = a.wad.read_bytes(); validate_wad(wad)
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    # Compile the exact checked header bytes. Quoted includes otherwise search
    # beside the adapter first and can select an unchecked, same-named header.
    adapter_path = out / 'gr3_doom.c'
    adapter_path.write_bytes((HERE / 'gr3_doom.c').read_bytes())
    (out / 'PureDOOM.h').write_bytes(engine)
    script = out / 'runtime.ld'
    script.write_text('SECTIONS { . = 0; .text : { *(.text*) } .rodata : { *(.rodata*) } '
                      '.data : { *(.data*) } .dynamic : { *(.dynamic) } .got : { *(.got*) } '
                      '.rel.dyn : { *(.rel.dyn) } .bss : { *(.bss*) *(COMMON) } '
                      '/DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) } }\n', encoding='ascii')
    flags = ['-target', 'arm-freestanding-eabi', '-mcpu=cortex_a9', '-marm', '-mfloat-abi=soft',
             '-Os', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fPIC',
             '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-nostdlib',
             '-Wno-incompatible-pointer-types', '-Wno-pointer-sign', '-Wno-parentheses',
             '-Wno-deprecated-non-prototype',
             '-Wl,-T,' + str(script), '-Wl,--entry=gr3_init']
    elf_path = out / 'doom.elf'
    object_path = out / 'doom.o'
    compile_flags = [f for f in flags if not f.startswith('-Wl,')]
    subprocess.run([sys.executable, '-m', 'ziglang', 'cc', *compile_flags, '-I', str(out),
                    '-c', str(adapter_path), '-o', str(object_path)], check=True)
    link_flags = ['-target', 'arm-freestanding-eabi', '-mcpu=cortex_a9', '-marm', '-mfloat-abi=soft',
                  '-nostdlib', '-fPIC', '-Wl,--entry=gr3_init']
    subprocess.run([sys.executable, '-m', 'ziglang', 'cc', *link_flags, '-Wl,-T,' + str(script),
                    str(object_path), '-o', str(elf_path)], check=True)
    with elf_path.open('rb') as stream:
        elf = ELFFile(stream)
        if elf['e_machine'] != 'EM_ARM': raise ValueError('Expected ARM ELF')
        sections = [s for s in elf.iter_sections() if s['sh_flags'] & 2 and s['sh_size']]
        memory_size = max(s['sh_addr'] + s['sh_size'] for s in sections)
        image = bytearray((memory_size + 15) & ~15)
        for s in sections:
            if s['sh_type'] != 'SHT_NOBITS': image[s['sh_addr']:s['sh_addr'] + s['sh_size']] = s.data()
        syms = list(elf.get_section_by_name('.symtab').iter_symbols())
        undefined = [s.name for s in syms if s.name and s['st_shndx'] == 'SHN_UNDEF']
        if undefined: raise ValueError('Unresolved symbols: ' + str(undefined))
        exports = {s.name: s['st_value'] for s in syms if s.name.startswith('gr3_') and s['st_info']['type'] == 'STT_FUNC'}
    # Zig 0.13 does not expose LLD's --emit-relocs. Link the same PIC program at
    # two bases instead. Every changed word must be an in-image absolute pointer
    # plus exactly the base delta; reject split instruction/address relocations.
    second_base = 0x10000000
    second_script = out / 'runtime-second.ld'
    second_script.write_text(script.read_text(encoding='ascii').replace('. = 0;', '. = 0x10000000;'), encoding='ascii')
    second_elf = out / 'doom-second.elf'
    subprocess.run([sys.executable, '-m', 'ziglang', 'cc', *link_flags, '-Wl,-T,' + str(second_script),
                    str(object_path), '-o', str(second_elf)], check=True)
    shifted = bytearray(len(image))
    with second_elf.open('rb') as stream:
        elf = ELFFile(stream)
        for s in elf.iter_sections():
            if s['sh_flags'] & 2 and s['sh_size']:
                start = s['sh_addr'] - second_base
                if start < 0 or start + s['sh_size'] > len(image): raise ValueError('Second link layout changed')
                if s['sh_type'] != 'SHT_NOBITS': shifted[start:start + s['sh_size']] = s.data()
    offsets = []
    for off in range(0, len(image), 4):
        old, new = struct.unpack_from('<I', image, off)[0], struct.unpack_from('<I', shifted, off)[0]
        if old != new:
            if old >= len(image) or new != old + second_base:
                raise ValueError(f'Non-pointer relocation at {off:#x}: {old:#x} -> {new:#x}')
            offsets.append(off)
    if not offsets or relocate(image, offsets, second_base) != shifted: raise ValueError('Relocation reconstruction failed')
    relocate(image, offsets, 0x68000000)  # Validate all runtime fixups before writing.
    (out / 'runtime.bin').write_bytes(image)
    (out / 'relocations.bin').write_bytes(b''.join(struct.pack('<I', x) for x in offsets))
    (out / 'doom1.wad').write_bytes(wad)
    report = dict(schema=1, engineCommit=ENGINE_COMMIT, engineSha256=ENGINE_SHA256,
                  adapterSha256=hashlib.sha256((HERE / 'gr3_doom.c').read_bytes()).hexdigest(),
                  imageBytes=len(image), imageSha256=hashlib.sha256(image).hexdigest(),
                  wadBytes=len(wad), wadSha256=hashlib.sha256(wad).hexdigest(),
                  relocations=offsets, exports=exports, arenaBytes=8 * 1024 * 1024,
                  hardwareTested=False, compilerFlags=flags)
    (out / 'runtime.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    build_camera(out, report)
    print(json.dumps({k: report[k] for k in ('imageBytes', 'wadBytes', 'imageSha256', 'hardwareTested')}))


def build_camera(out, report):
    from elftools.elf.elffile import ELFFile
    header = [f'#define DOOM_IMAGE_BYTES {report["imageBytes"]}u',
              f'#define DOOM_WAD_BYTES {report["wadBytes"]}u',
              f'#define DOOM_FIXUP_COUNT {len(report["relocations"])}u']
    header += [f'#define OFFSET_{name} {value}u' for name, value in report['exports'].items()]
    (out / 'runtime-offsets.h').write_text('\n'.join(header) + '\n', encoding='ascii')
    # Zig's assembler cache does not track .incbin dependencies. Bind their
    # content hashes into the assembly source to invalidate stale asset objects.
    assets = ['/* embedded content: ' + report['imageSha256'] + ' ' + report['wadSha256'] +
              ' ' + hashlib.sha256((out / 'relocations.bin').read_bytes()).hexdigest() + ' */']
    for symbol, file in [('doom_image', 'runtime.bin'), ('doom_fixups', 'relocations.bin'), ('doom_wad', 'doom1.wad')]:
        assets += ['.section .rodata', '.balign 16', f'.global {symbol}', f'{symbol}:', f'.incbin "{(out / file).as_posix()}"']
    asset_source = out / 'assets.S'
    asset_source.write_text('\n'.join(assets) + '\n', encoding='ascii')
    address = 0x540c0000
    script = out / 'camera.ld'
    script.write_text(f'SECTIONS {{ . = {address:#x}; .text : {{ *(.text*) *(.rodata*) }} '
                      '/DISCARD/ : { *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) } }\n', encoding='ascii')
    flags = ['-target', 'arm-freestanding-eabi', '-mcpu=cortex_a9', '-marm', '-mfloat-abi=soft',
             '-Os', '-g', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-fno-pic',
             '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-nostdlib', '-Wall', '-Wextra', '-Werror']
    elf_path = out / 'camera.elf'
    exports_required = ['camera_open', 'camera_try_open', 'camera_construct', 'camera_destroy',
                        'camera_cleanup', 'camera_draw', 'camera_filter', 'camera_event', 'camera_tick', 'camera_call']
    keep = ['-Wl,-u,' + name for name in exports_required]
    subprocess.run([sys.executable, '-m', 'ziglang', 'cc', *flags, '-I', str(out), str(HERE / 'camera.c'),
                    str(asset_source), *keep, '-Wl,-T,' + str(script), '-Wl,--entry=camera_open', '-o', str(elf_path)], check=True)
    with elf_path.open('rb') as stream:
        elf = ELFFile(stream)
        for s in elf.iter_sections():
            if s.name in ('.data', '.bss', '.got') and s['sh_size']: raise ValueError('Launcher has mutable static storage')
        symbols = list(elf.get_section_by_name('.symtab').iter_symbols())
        if any(s.name and s['st_shndx'] == 'SHN_UNDEF' for s in symbols): raise ValueError('Launcher unresolved symbols')
        exports = {s.name: s['st_value'] for s in symbols if s.name.startswith('camera_') and s['st_info']['type'] == 'STT_FUNC'}
        asset_addresses = {s.name: s['st_value'] for s in symbols if s.name in ('doom_image', 'doom_fixups', 'doom_wad')}
        code = elf.get_section_by_name('.text').data()
    code += bytes(-len(code) % 4)
    embedded_assets = {}
    for symbol, file in [('doom_image', 'runtime.bin'), ('doom_fixups', 'relocations.bin'), ('doom_wad', 'doom1.wad')]:
        expected = (out / file).read_bytes()
        start = asset_addresses[symbol] - address
        if code[start:start + len(expected)] != expected: raise ValueError('Stale or incorrect embedded asset: ' + symbol)
        embedded_assets[symbol] = dict(address=asset_addresses[symbol], bytes=len(expected), sha256=hashlib.sha256(expected).hexdigest())
    (out / 'camera.bin').write_bytes(code)
    def branch(at, target, link=False):
        delta = target - at - 8
        if delta % 4 or not -0x2000000 <= delta < 0x2000000: raise ValueError('ARM branch range')
        return (0xeb000000 if link else 0xea000000) | ((delta >> 2) & 0xffffff)
    patches = [dict(address=0x53000460, expected=0x55804374, replacement=0x558043c0, reason='Clear reserved owner word before native heap'),
               dict(address=0x5316fa94, expected=0xe300069c, replacement=0xe30006c0, reason='Extend live-view controller for owned DOOM state')]
    for at, expected, symbol, link in [(0x5316faa0, 0xeb000dd7, 'camera_construct', True),
                                       (0x53170b50, 0xe1a0c00d, 'camera_destroy', False),
                                       (0x5316d194, 0xeb08925e, 'camera_draw', True),
                                       (0x532231e4, 0xe1d130b0, 'camera_event', False),
                                       (0x53227114, 0xe1a0c00d, 'camera_open', False)]:
        patches.append(dict(address=at, expected=expected, replacement=branch(at, exports[symbol], link), reason=symbol))
    manifest = dict(schema=1, address=address, bytes=len(code), sha256=hashlib.sha256(code).hexdigest(),
                    sourceSha256=hashlib.sha256((HERE / 'camera.c').read_bytes()).hexdigest(),
                    runtimeSha256=report['imageSha256'], wadSha256=report['wadSha256'],
                    exports=exports, assets=embedded_assets, patches=patches, hardwareTested=False)
    (out / 'camera.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
