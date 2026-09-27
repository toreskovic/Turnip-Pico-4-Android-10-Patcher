#!/usr/bin/env python3
"""Convert a GameNative ARM64 Turnip ZIP using an Android 10 C11 threads shim."""
from __future__ import annotations

import argparse
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
import zipfile

VERSION = '1.0.0'
SUFFIX = '-Pico-A10-compat'
SHIM = 'libandroid_threads_compat.so'
REPORT = 'pico-a10-patch.json'
NOTICE = 'PICO-A10-NDK-LICENSE.txt'
SUPPORTED = frozenset('call_once mtx_lock mtx_unlock mtx_init mtx_destroy cnd_init '
                      'cnd_destroy thrd_create cnd_broadcast cnd_wait cnd_signal '
                      'thrd_join thrd_yield thrd_current'.split())
ROOT = Path(__file__).resolve().parent


class ConversionError(Exception):
    pass


def find_patchelf(override: str | None) -> Path:
    if override:
        found = shutil.which(override)
        if not found:
            raise ConversionError(f'Cannot find executable patchelf: {override}')
        return Path(found).resolve()
    # Resolve the wheel's executable even when this environment is not activated
    # or pip installed it into a user scripts directory outside PATH.
    try:
        package = metadata.distribution('patchelf')
    except metadata.PackageNotFoundError:
        package = None
    if package is not None:
        for entry in package.files or ():
            if entry.name == 'patchelf':
                candidate = Path(package.locate_file(entry))
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return candidate.resolve()
    found = shutil.which('patchelf')
    if found:
        return Path(found).resolve()
    raise ConversionError('patchelf not found. Run python -m pip install -r requirements.txt '
                          'with the Python environment used for this script, '
                          'or pass --patchelf PATH.')


def run(*args: object) -> str:
    try:
        proc = subprocess.run([str(a) for a in args], capture_output=True, text=True,
                              env={**os.environ, 'LC_ALL': 'C'})
    except OSError as exc:
        raise ConversionError(f'Cannot run {args[0]}: {exc}') from exc
    if proc.returncode:
        raise ConversionError(f'{Path(str(args[0])).name} failed:\n{proc.stderr.strip() or proc.stdout.strip()}')
    return proc.stdout


def safe_name(name: str) -> bool:
    # GameNative's importer expects flat ZIPs and uses meta.name as a directory.
    return (bool(name.strip()) and name not in ('.', '..') and
            not any(c in name for c in '/\\:') and
            not any(ord(c) < 32 or ord(c) == 127 for c in name))


def read_package(archive: Path, dest: Path) -> tuple[dict, list[str]]:
    with zipfile.ZipFile(archive) as z:
        entries = z.infolist()
        if len(entries) > 1024 or sum(e.file_size for e in entries) > 512 * 1024**2:
            raise ConversionError('ZIP exceeds the 1024-file / 512 MiB unpacked limit.')
        names: list[str] = []
        seen: set[str] = set()
        for e in entries:
            if not safe_name(e.filename) or e.is_dir():
                raise ConversionError(f'Expected a flat GameNative ZIP; unsupported entry: {e.filename!r}')
            if e.filename.casefold() in seen:
                raise ConversionError(f'Duplicate ZIP filename: {e.filename}')
            seen.add(e.filename.casefold())
            if stat.S_ISLNK(e.external_attr >> 16) or e.flag_bits & 1:
                raise ConversionError('Symlinks and encrypted ZIP entries are not supported.')
            if e.filename.casefold() in {SHIM.casefold(), REPORT.casefold(), NOTICE.casefold()}:
                raise ConversionError('Package already contains compatibility-patch files; use the original ZIP.')
            names.append(e.filename)
        if 'meta.json' not in names:
            raise ConversionError('ZIP must contain meta.json at its root.')
        if z.getinfo('meta.json').file_size > 1024**2:
            raise ConversionError('meta.json exceeds 1 MiB.')
        meta = json.loads(z.read('meta.json').decode('utf-8-sig'))
        if not isinstance(meta, dict):
            raise ConversionError('meta.json must be a JSON object.')
        for key in ('name', 'libraryName'):
            if not isinstance(meta.get(key), str) or not safe_name(meta[key]):
                raise ConversionError(f'meta.json has an invalid {key}.')
        if meta['libraryName'] not in names or meta['libraryName'] == 'meta.json':
            raise ConversionError('The driver declared by libraryName is missing from the ZIP.')
        if 'description' in meta and not isinstance(meta['description'], str):
            raise ConversionError('meta.json description must be text.')
        for e in entries:
            with z.open(e) as src, (dest / e.filename).open('wb') as out:
                shutil.copyfileobj(src, out)
    return meta, names


def check_elf(path: Path) -> None:
    with path.open('rb') as f:
        header = f.read(64)
    if (len(header) < 64 or header[:6] != b'\x7fELF\x02\x01' or
            struct.unpack_from('<HH', header, 16) != (3, 183)):
        raise ConversionError(f'{path.name}: expected a little-endian ARM64 ELF shared library.')


def symbols(readelf: Path, path: Path, undefined: bool) -> set[tuple[str, str | None]]:
    result = set()
    for line in run(readelf, '--dyn-syms', '--wide', path).splitlines():
        parts = line.split()
        if len(parts) < 8 or not re.fullmatch(r'\d+:', parts[0]):
            continue
        if (parts[6] == 'UND') != undefined:
            continue
        name, _, version = parts[7].replace('@@', '@').partition('@')
        result.add((name, version or None))
    return result


def find_ndk(explicit: Path | None) -> Path:
    if explicit:
        candidates = [explicit]
    else:
        candidates = [Path(os.environ[k]) for k in ('ANDROID_NDK_HOME', 'ANDROID_NDK_ROOT', 'NDK_HOME')
                      if os.environ.get(k)]
        sdks = [Path(os.environ[k]) for k in ('ANDROID_SDK_ROOT', 'ANDROID_HOME') if os.environ.get(k)]
        sdks += [Path.home() / 'Android/sdk', Path.home() / 'Library/Android/sdk']
        for sdk in sdks:
            candidates += sorted((sdk / 'ndk').glob('*'),
                                 key=lambda p: tuple(int(n) for n in re.findall(r'\d+', p.name)), reverse=True)
            candidates.append(sdk / 'ndk-bundle')
    for candidate in candidates:
        if (candidate / 'toolchains/llvm/prebuilt').is_dir():
            return candidate.resolve()
    raise ConversionError('Android NDK not found. Pass --ndk PATH or set ANDROID_NDK_HOME.')


def toolchain(ndk: Path) -> tuple[Path, Path, Path]:
    host = {'Linux': 'linux-x86_64', 'Darwin': 'darwin-x86_64'}.get(platform.system())
    if not host:
        raise ConversionError('Use Linux, WSL2 (with a Linux NDK), or macOS; native Windows is not supported.')
    base = ndk / 'toolchains/llvm/prebuilt' / host
    cc = base / 'bin/aarch64-linux-android29-clang'
    readelf = base / 'bin/llvm-readelf'
    if not cc.is_file() or not readelf.is_file():
        raise ConversionError(f'NDK lacks the {host} ARM64/API-29 toolchain: {base}')
    return cc, readelf, base / 'sysroot'


def libc_exports(readelf: Path, sysroot: Path) -> set[tuple[str, str | None]]:
    exports = set()
    for library in ('libc.so', 'libm.so', 'libdl.so'):
        exports |= symbols(readelf, sysroot / 'usr/lib/aarch64-linux-android/29' / library, False)
    return exports


def check_imports(imports: set, available: set, patched: set[str], label: str) -> None:
    incompatible = sorted(f'{name}@{version}' for name, version in imports
                          if version and version.startswith('LIBC') and
                          (name, version) not in available and not (version == 'LIBC_R' and name in patched))
    if incompatible:
        raise ConversionError(f'{label}: unsupported Android system imports: {", ".join(incompatible)}. '
                              'This tool only fixes the supported C11 threading imports.')


def sha256(path: Path) -> str:
    with path.open('rb') as f:
        digest = hashlib.sha256()
        for chunk in iter(lambda: f.read(1024**2), b''):
            digest.update(chunk)
        return digest.hexdigest()


def convert(archive: Path, output: Path, ndk_arg: Path | None, patchelf_arg: str | None,
            suffix: str = SUFFIX) -> dict:
    archive = archive.resolve()
    output = output.resolve()
    if archive == output or output.exists():
        raise ConversionError(f'Refusing to overwrite input or existing output: {output}')
    if not suffix or not safe_name('driver' + suffix):
        raise ConversionError('Suffix must be nonempty and must not contain path separators/control characters.')
    if not output.parent.is_dir():
        raise ConversionError(f'Output directory does not exist: {output.parent}')
    with tempfile.TemporaryDirectory(prefix='.pico-a10-', dir=output.parent) as tmp:
        work = Path(tmp) / 'payload'
        work.mkdir()
        meta, files = read_package(archive, work)
        if meta['name'].endswith(suffix):
            raise ConversionError('Driver name already has this suffix; use the original ZIP.')
        driver = work / meta['libraryName']
        check_elf(driver)
        ndk = find_ndk(ndk_arg)
        cc, readelf, sysroot = toolchain(ndk)
        patchelf = find_patchelf(patchelf_arg)
        # --help writes to stderr in some releases, so inspect both streams.
        help_proc = subprocess.run([str(patchelf), '--help'], capture_output=True, text=True)
        if '--clear-symbol-version' not in help_proc.stdout + help_proc.stderr:
            raise ConversionError('This patchelf lacks --clear-symbol-version; install a recent release.')
        available = libc_exports(readelf, sysroot)
        imports = symbols(readelf, driver, True)
        targets = {name for name, version in imports if name in SUPPORTED and version in (None, 'LIBC_R')}
        check_imports(imports, available, targets, driver.name)
        if not targets:
            raise ConversionError('No supported C11 imports need this patch. No output was created; '
                                  'this is not a general Android API downgrader.')
        for name in files:
            candidate = work / name
            if candidate != driver and candidate.suffix == '.so':
                check_elf(candidate)
                deps = symbols(readelf, candidate, True)
                check_imports(deps, available, set(), name)
                if any(n in SUPPORTED and v is None for n, v in deps):
                    raise ConversionError(f'{name}: companion library also needs C11 patching; unsupported package.')
        shim = work / SHIM
        run(cc, '-shared', '-fPIC', '-O2', '-Wl,-z,defs', '-Wl,-soname,' + SHIM,
            ROOT / 'src/threads_compat.c', '-o', shim)
        exports = symbols(readelf, shim, False)
        if not targets <= {name for name, _ in exports}:
            raise ConversionError('Built shim is missing required exports.')
        check_imports(symbols(readelf, shim, True), available, set(), SHIM)
        original_hash = sha256(driver)
        original_needed = run(patchelf, '--print-needed', driver).splitlines()
        if SHIM in original_needed:
            raise ConversionError('Driver is already patched; use the original ZIP.')
        original_rpath = run(patchelf, '--print-rpath', driver).strip()
        paths = [p for p in original_rpath.split(':') if p]
        if '$ORIGIN' not in paths:
            paths.insert(0, '$ORIGIN')
        args = [patchelf, '--add-needed', SHIM, '--set-rpath', ':'.join(paths)]
        versioned = sorted(name for name, version in imports if name in targets and version == 'LIBC_R')
        for name in versioned:
            args += ['--clear-symbol-version', name]
        run(*args, driver)
        after = symbols(readelf, driver, True)
        expected = {(name, None if name in targets and version == 'LIBC_R' else version)
                    for name, version in imports}
        if after != expected:
            raise ConversionError('Post-patch verification failed: unexpected symbol changes.')
        needed = run(patchelf, '--print-needed', driver).splitlines()
        if sorted(needed) != sorted(original_needed + [SHIM]):
            raise ConversionError('Post-patch verification failed: unexpected dependencies.')
        if run(patchelf, '--print-rpath', driver).strip() != ':'.join(paths):
            raise ConversionError('Post-patch verification failed: incorrect RUNPATH.')
        original_meta = dict(meta)
        meta['name'] += suffix
        meta['minApi'] = 29
        meta['description'] = (meta.get('description', '').rstrip() + '\n\n'
            'Pico / Android 10 compatibility: C11 threading shim. GPU feature support is unchanged.').lstrip()
        (work / 'meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        header = sysroot / 'usr/include/bits/threads_inlines.h'
        (work / NOTICE).write_text(header.read_text().split('*/', 1)[0] + '*/\n', encoding='utf-8')
        info = dict(converter_version=VERSION, original_metadata=original_meta,
                    input_archive_sha256=sha256(archive), original_driver_sha256=original_hash,
                    patched_driver_sha256=sha256(driver), shim_sha256=sha256(shim),
                    shim_source_sha256=sha256(ROOT / 'src/threads_compat.c'),
                    shim_symbols=sorted(targets), cleared_symbol_versions=versioned,
                    original_needed=original_needed, original_rpath=original_rpath,
                    ndk=(ndk / 'source.properties').read_text().strip(),
                    patchelf=run(patchelf, '--version').strip(), target_api=29)
        (work / REPORT).write_text(json.dumps(info, indent=2) + '\n', encoding='utf-8')
        result = Path(tmp) / 'result.zip'
        with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as z:
            for name in files + [SHIM, REPORT, NOTICE]:
                z.write(work / name, name)
        # Same filesystem: atomic publication without overwriting a concurrently created output.
        os.link(result, output)
        return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('driver_zip', type=Path, help='Original GameNative driver ZIP (never modified)')
    parser.add_argument('-o', '--output', type=Path, help='Output ZIP; default: input filename plus suffix')
    parser.add_argument('--suffix', default=SUFFIX, help=f'Driver/archive name suffix (default: {SUFFIX})')
    parser.add_argument('--ndk', type=Path, help='Android NDK root; otherwise detected from environment/SDK')
    parser.add_argument('--patchelf', help='patchelf executable (default: PyPI package in this Python environment, then PATH)')
    parser.add_argument('--version', action='version', version=VERSION)
    args = parser.parse_args()
    try:
        if not args.suffix or not safe_name('driver' + args.suffix):
            raise ConversionError('Invalid suffix: use nonempty text without path separators/control characters.')
        output = args.output or args.driver_zip.with_name(args.driver_zip.stem + args.suffix + '.zip')
        info = convert(args.driver_zip, output, args.ndk, args.patchelf, args.suffix)
    except (ConversionError, OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 1
    print(f'Created: {output.resolve()}')
    print(f'Driver: {info["original_metadata"]["name"]}{args.suffix}')
    print(f'Patched C11 imports: {", ".join(info["shim_symbols"])}')
    print('Static checks passed. Import the ZIP into GameNative and test on the headset.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
