"""Offline backup/restore of a stopped appdata directory, without overwriting data."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

MANIFEST = "__panwatch_backup_manifest__.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def backup(source, archive, *, stopped_confirmed=False):
    source, archive = Path(source).resolve(), Path(archive).resolve()
    if not stopped_confirmed:
        raise ValueError("stop all writers and confirm before backup")
    if not source.is_dir() or archive == source or source in archive.parents:
        raise ValueError("archive must be outside the source directory")
    files = sorted(source.rglob("*"))
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in files):
        raise ValueError("symlinks/junctions are not backed up")
    if (source / MANIFEST).exists():
        raise ValueError("reserved manifest name in source")
    manifest = {}
    # 'x' refuses to overwrite any previous backup.
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in files:
            if path.is_file():
                name = path.relative_to(source).as_posix()
                data = path.read_bytes()
                bundle.writestr(name, data)
                manifest[name] = digest(data)
        bundle.writestr(MANIFEST, json.dumps(manifest, sort_keys=True))
    verify(archive)
    return manifest


def verify(archive):
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        if len(names) != len(set(names)) or MANIFEST not in names:
            raise ValueError("missing manifest or duplicate archive member")
        manifest = json.loads(bundle.read(MANIFEST))
        if set(names) != set(manifest) | {MANIFEST}:
            raise ValueError("manifest member mismatch")
        for name, expected in manifest.items():
            path = PurePosixPath(name)
            if (path.is_absolute() or ".." in path.parts or ":" in name or "\\" in name
                    or path.as_posix() != name or not path.parts):
                raise ValueError("unsafe archive path")
            if digest(bundle.read(name)) != expected:
                raise ValueError("checksum mismatch")
    return manifest


def restore(archive, destination):
    manifest = verify(archive)
    destination = Path(destination).resolve()
    # New directory only; there is no in-place database rollback.
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for name in manifest:
            target = destination.joinpath(*PurePosixPath(name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as stream:
                stream.write(bundle.read(name))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("backup")
    create.add_argument("source")
    create.add_argument("archive")
    create.add_argument("--stopped-confirmed", action="store_true")
    check = sub.add_parser("verify")
    check.add_argument("archive")
    recover = sub.add_parser("restore")
    recover.add_argument("archive")
    recover.add_argument("destination")
    args = parser.parse_args()
    if args.command == "backup":
        result = backup(args.source, args.archive, stopped_confirmed=args.stopped_confirmed)
    elif args.command == "restore":
        result = restore(args.archive, args.destination)
    else:
        result = verify(args.archive)
    print(f"{args.command}: {len(result)} files verified")


if __name__ == "__main__":
    main()
