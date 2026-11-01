"""Run the complete suite, build and probe a local GR III 2.10 candidate.

Requires user-supplied firmware, engine header and IWAD. Never accesses a camera.
Use a new --out directory for every run; partial evidence is kept on failure.
"""
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ('engine', 'wad', 'firmware', 'out'):
        ap.add_argument('--' + name, type=Path, required=True)
    a = ap.parse_args()
    engine, wad, official, out = (p.resolve() for p in (a.engine, a.wad, a.firmware, a.out))
    for path in (engine, wad, official):
        if not path.is_file(): ap.error(f'Missing input: {path}')
    out.mkdir(parents=True, exist_ok=False)
    runtime, candidate = out / 'runtime', out / 'firmware'

    def run(label, *command):
        print('\n' + label, flush=True)
        subprocess.run([str(x) for x in command], cwd=ROOT, check=True)

    python = sys.executable
    run('Container suite (150 synthetic parser cases)', 'node', '--experimental-transform-types',
        '--test', 'tests/container.test.mjs')
    run('Host relocation and IWAD suite', python, '-m', 'unittest', 'discover', '-s', 'tools', '-p', 'test_build.py', '-v')
    run('Build ARM runtime and camera launcher', python, 'tools/build.py', '--engine', engine, '--wad', wad, '--out', runtime)
    run('Actual ARM controls', python, 'tools/test_controls.py', runtime, '-v')
    run('Actual ARM watermark pixels', python, 'tools/test_watermark.py', runtime, '-v')
    run('Actual ARM gameplay, relocation and blitter', python, 'tools/verify.py', runtime)
    run('Build and re-decode guarded firmware container', 'node', '--experimental-transform-types',
        'tools/pack.mjs', official, runtime, candidate)
    run('Packaged camera hooks, ownership and exit', python, 'tools/verify_camera.py', runtime, candidate)
    run('Native updater and BOOT loader (both banks)', python, 'vendor/grmod/loader_probe.py',
        '--rtos', candidate / 'base-rtos.bin', '--boot', candidate / 'boot.bin', '--official', official,
        '--container', candidate / 'candidate.bin', '--build-report', candidate / 'candidate.json',
        '--report', candidate / 'loader-verification.json')
    raw = (candidate / 'candidate.bin').read_bytes()
    manifest = json.loads((candidate / 'candidate.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(raw).hexdigest()
    assert digest == manifest['outputSha256']
    # Camera filename is offered only after the entire suite succeeds.
    target = candidate / 'fwdc239b.bin'
    with target.open('xb') as stream: stream.write(raw)
    assert target.read_bytes() == raw
    report = dict(fullSuitePassed=True, candidateSha256=digest, candidateBytes=len(raw),
                  firmwareFilename=target.name, hardwareTested=False,
                  engineCommit='355cfbd16fac119718879239336ee2ea408886bd')
    (out / 'check.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print('\nAll checks passed. Camera filename: ' + str(target), flush=True)
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
