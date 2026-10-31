#!/usr/bin/env python3
"""Publish the supplied Beta 8.2 build; no application compilation or binary edits."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile


REPOSITORY = "malifica/TGC-Designer-Tools"
BRANCH = "release/beta8.2-publication"
PREPARED_SOURCE = "d1f31128ccfeb964a3f8ebaf800a9ca415cc26be"
CONTROL_BASE = "d1f31128ccfeb964a3f8ebaf800a9ca415cc26be"
OLD_TAG = "v0.5.0-2k25-beta8.1"
OLD_SOURCE = "67980485fd0639e3458382487ed1fee831de078d"
TAG = "v0.5.0-2k25-beta8.2"
TITLE = "TGC Designer Tools 2K25 - Beta 8.2"
EXE = "tgc_gui_2k25_beta8_2.exe"
EXE_BYTES = 194213555
EXE_SHA = "895e520f068bd72ecbbd9ecb31516de0eb3e8ade37c7ed43be8e47c9c245ad7b"
PACKAGE = "TGC-Designer-Tools-2K25-v0.5.0-2k25-beta8.2-Windows-x64.zip"
NOTES = "RELEASE_NOTES_v0.5.0-2k25-beta8.2.md"
BUILD_MANIFEST = "BETA8_2_BUILD_SOURCE_MANIFEST.json"
BUILD_VALIDATION = "BETA8_2_BUILD_VALIDATION.json"
UPLOAD_MANIFEST = "BETA8_2_UPLOAD_MANIFEST.json"
WINDOWS_RECEIPT = "BETA8_2_WINDOWS_BUILD_RECEIPT.json"
WORKFLOW = ".github/workflows/publish-existing-beta82.yml"
SCRIPT = ".github/publication/publish_beta82.py"
CONFIG = ".github/publication/beta82-transport.json"
BASE_EXE = {
    "url": "https://github.com/" + REPOSITORY + "/releases/download/" + OLD_TAG + "/tgc_gui_2k25_beta8_1.exe",
    "bytes": 194211815,
    "sha256": "d05d4e17e59a4e69d7185d411341cef9b3c713ad6e6fc4e48101c63aec9f37d4",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(path, expected):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), "Missing or unsafe file: " + str(path))
    require(path.stat().st_size == expected["bytes"], "Size mismatch: " + path.name)
    require(digest(path) == expected["sha256"], "SHA-256 mismatch: " + path.name)


def bytes_record(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def path_record(path):
    return {"bytes": Path(path).stat().st_size, "sha256": digest(path)}


def safe_name(name):
    path = PurePosixPath(name)
    return (isinstance(name, str) and bool(name) and not path.is_absolute()
            and ".." not in path.parts and ".git" not in path.parts
            and "\\" not in name and "\x00" not in name and ":" not in name)


def git(*arguments, binary=False):
    raw = subprocess.check_output(["git", *arguments])
    return raw if binary else raw.decode("utf-8").strip()


def api(path, method="GET", data=None, allow_missing=False):
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": "Bearer " + os.environ["GH_TOKEN"],
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = None if data is None else json.dumps(data).encode("utf-8")
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPOSITORY + "/" + path,
        data=payload, headers=headers, method=method,
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_missing:
                return None
            if method != "GET" or error.code not in (429, 500, 502, 503, 504) or attempt == 4:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("GitHub request did not finish")


def public_download(url, destination, expected=None):
    """Use an independent urllib request with no authorization header."""
    require(url.startswith("https://github.com/" + REPOSITORY + "/"), "Unexpected public URL")
    request = urllib.request.Request(url, headers={"User-Agent": "TGC-Beta8.2-release-verification"})
    require("Authorization" not in request.headers, "Public request unexpectedly carries authorization")
    destination = Path(destination)
    for attempt in range(5):
        try:
            with urllib.request.urlopen(request, timeout=240) as response, destination.open("wb") as output:
                shutil.copyfileobj(response, output, length=1024 * 1024)
            if expected is not None:
                check(destination, expected)
            return path_record(destination)
        except urllib.error.HTTPError as error:
            if error.code not in (404, 429, 500, 502, 503, 504) or attempt == 4:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Public download did not finish")


def fetch_blob(entry):
    sha = entry["git_blob_sha"]
    require(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "Invalid Git blob SHA")
    obj = api("git/blobs/" + sha)
    require(obj["encoding"] == "base64", "Unexpected Git blob encoding")
    raw = base64.b64decode(obj["content"])
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    require(actual == sha, "Git blob object checksum mismatch")
    require(bytes_record(raw) == {key: entry[key] for key in ("bytes", "sha256")}, "Transport chunk checksum mismatch")
    return raw


def assemble(record, folder):
    name = record["name"]
    require(safe_name(name) and PurePosixPath(name).name == name, "Invalid transport filename")
    output = folder / name
    chunks = record["chunks"]
    require(chunks and sum(c["bytes"] for c in chunks) == record["bytes"], "Invalid transport chunk sizes")
    with output.open("wb") as stream, concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0, len(chunks), 8):
            for raw in pool.map(fetch_blob, chunks[offset:offset + 8]):
                stream.write(raw)
    check(output, record)
    print("Verified transported file:", name, record["bytes"], record["sha256"], flush=True)
    return output


def restore_executable(record, folder):
    expected = {"name": EXE, "bytes": EXE_BYTES, "sha256": EXE_SHA}
    require(all(record[key] == value for key, value in expected.items()), "Unexpected supplied executable")
    if "chunks" in record:
        return assemble(record, folder)
    require(record["method"] == "copy-recipe-v1", "Unsupported executable transport")
    recipe = json.loads(assemble(record["recipe"], folder).read_text(encoding="utf-8"))
    literals = assemble(record["literal"], folder)
    require(recipe["format"] == "tgc-exact-byte-transfer-v1", "Unsupported exact-byte recipe")
    require(recipe["target"] == expected and recipe["base"] == BASE_EXE, "Exact-byte recipe provenance changed")
    require(all(record["literal"][key] == recipe["literal"][key] for key in ("name", "bytes", "sha256")), "Literal payload provenance changed")
    base = folder / "beta81-public-reference.exe"
    public_download(BASE_EXE["url"], base, BASE_EXE)
    sources = {"copy": base, "literal": literals}
    require(sum(s["length"] for s in recipe["segments"]) == EXE_BYTES, "Recipe target length mismatch")
    output = folder / EXE
    opened = {key: (path.open("rb"), path.stat().st_size) for key, path in sources.items()}
    try:
        with output.open("wb") as destination:
            for segment in recipe["segments"]:
                require(segment["kind"] in opened, "Invalid recipe source")
                stream, size = opened[segment["kind"]]
                offset, length = segment["offset"], segment["length"]
                require(type(offset) is int and type(length) is int and offset >= 0 and length > 0 and offset + length <= size, "Recipe segment exceeds source")
                stream.seek(offset)
                remaining = length
                while remaining:
                    raw = stream.read(min(remaining, 1024 * 1024))
                    require(raw, "Unexpected end of byte-reference source")
                    destination.write(raw)
                    remaining -= len(raw)
    finally:
        for stream, _ in opened.values():
            stream.close()
    check(output, expected)
    print("Verified original supplied executable, unchanged:", EXE_BYTES, EXE_SHA, flush=True)
    return output


def validate_config(config):
    require(config["version"] == 1 and config["repository"] == REPOSITORY, "Wrong publication configuration")
    require(config["branch"] == BRANCH and config["control_base_sha"] == CONTROL_BASE, "Wrong publication control branch")
    require(config["tag"] == TAG and config["title"] == TITLE, "Wrong release identity")
    require(config["expected_main_sha"] == config["source_sha"], "Release source must be reviewed main")
    for key, name in (("notes", NOTES), ("build_manifest", BUILD_MANIFEST), ("uploaded_manifest", UPLOAD_MANIFEST),
                      ("build_validation", BUILD_VALIDATION), ("windows_build_receipt", WINDOWS_RECEIPT)):
        require(config[key]["name"] == name, "Wrong release evidence filename: " + key)
    require(len(config["matching_source_files"]) == 142, "Unexpected matching source count")
    required = {NOTES, "tgc_beta8_entry.py", "OSMTGC.py", "tgc_unity_raw_svg.py", "VERIFY_BETA8_2_PARKING.py",
                "BUILD_TGC_2K25_BETA8_2.py", "COLLECT_BETA8_2_FOR_PUBLICATION.py", "tgc_gui.py", "osm_mask_alignment.py"}
    require(required <= config["matching_source_files"].keys(), "Required matching source omitted")
    require(config["exe"]["sha256"] == EXE_SHA and config["exe"]["bytes"] == EXE_BYTES and config["exe"]["name"] == EXE, "Wrong existing build")
    for sha in (config["source_sha"], config["source_tree_sha"]):
        require(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "Invalid source Git object")
    return config


def source_tree(source_sha, destination):
    """Read the source commit without checkout filters or application execution."""
    entries = {}
    raw_tree = git("ls-tree", "-rz", "--full-tree", source_sha, binary=True)
    for record in raw_tree.split(b"\0"):
        if not record:
            continue
        metadata, encoded_name = record.split(b"\t", 1)
        mode, kind, blob_sha = metadata.decode("ascii").split()
        name = encoded_name.decode("utf-8")
        require(safe_name(name) and kind == "blob" and mode in ("100644", "100755"), "Unsupported source tree entry: " + name)
        require(not name.startswith(".github/publication/") and name not in (WORKFLOW, ".github/workflows/prepare-beta82-source.yml"), "Control files are present in release source")
        raw = git("cat-file", "blob", blob_sha, binary=True)
        require(hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest() == blob_sha, "Source Git blob changed")
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        entries[name] = {**bytes_record(raw), "git_blob_sha": blob_sha, "mode": mode}
    return entries


def verify_supplied_manifest(root, config):
    original = json.loads((root / UPLOAD_MANIFEST).read_bytes())
    require(original["version"] == 1 and original["exe"] == "dist/" + EXE, "Unexpected original upload manifest")
    require(original["format"] == "TGC Beta 8.2 existing-build publication input", "Wrong collector format")
    require(original["rebuild_performed"] is False and original["source_files_modified"] is False, "Collector did not preserve inputs")
    receipt = json.loads((root / WINDOWS_RECEIPT).read_bytes())
    expected = dict(config["matching_source_files"])
    require(receipt["schema"] == "tgc-windows-build-inputs-v1" and receipt["release"] == TAG, "Wrong Windows build receipt")
    require(receipt["source_and_support"] == expected, "Windows build input hashes differ from reviewed source")
    exe_path = "dist/" + EXE
    expected[exe_path] = {"bytes": EXE_BYTES, "sha256": EXE_SHA}
    require(receipt["exe"] == {"path": exe_path, **expected[exe_path]}, "Windows build receipt describes a different executable")
    expected[exe_path + ".build.json"] = path_record(root / WINDOWS_RECEIPT)
    expected[exe_path + ".sha256.txt"] = bytes_record((EXE_SHA + "  " + EXE + "\n").encode("ascii"))
    require(original["files"] == expected, "Publication input records differ from the original upload manifest")


def package_assets(root, publication, executable, config):
    assets = publication / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    target_exe = assets / EXE
    shutil.copyfile(executable, target_exe)
    check(target_exe, config["exe"])
    members = {
        EXE: target_exe,
        NOTES: root / NOTES,
        "LICENSE": root / "LICENSE",
        "laszip/LICENSE.txt": root / "laszip/LICENSE.txt",
        "splines.json": root / "extras/splines.json",
        BUILD_MANIFEST: root / BUILD_MANIFEST,
        BUILD_VALIDATION: root / BUILD_VALIDATION,
        WINDOWS_RECEIPT: root / WINDOWS_RECEIPT,
        UPLOAD_MANIFEST: root / UPLOAD_MANIFEST,
    }
    for name in sorted(config["matching_source_files"]):
        if name.startswith("tree_profiles/"):
            members[name] = root / name
    source_record = {
        "repository": REPOSITORY, "tag": TAG,
        "source_commit": config["source_sha"], "source_tree": config["source_tree_sha"],
        "supplied_executable": {"name": EXE, "bytes": EXE_BYTES, "sha256": EXE_SHA},
        "original_archive": config["original_archive"],
        "build_source_manifest": config["build_manifest"],
        "original_windows_build_receipt": config["windows_build_receipt"],
        "release_packaging_rebuilt_executable": False,
    }
    source_record_path = publication / "RELEASE_SOURCE.json"
    source_record_path.write_text(json.dumps(source_record, indent=2) + "\n", encoding="utf-8", newline="\n")
    members["RELEASE_SOURCE.json"] = source_record_path
    expected_members = {name: path_record(path) for name, path in sorted(members.items())}
    archive = assets / PACKAGE
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for name, path in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 31, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source, zipped.open(info, "w", force_zip64=True) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    verify_windows_package(archive, expected_members)
    for asset in (target_exe, archive):
        (assets / (asset.name + ".sha256.txt")).write_text(digest(asset) + "  " + asset.name + "\n", encoding="ascii", newline="\n")
    uploaded_files = json.loads((root / UPLOAD_MANIFEST).read_bytes())["files"]
    check(assets / (EXE + ".sha256.txt"), uploaded_files["dist/" + EXE + ".sha256.txt"])
    asset_names = {EXE, PACKAGE, EXE + ".sha256.txt", PACKAGE + ".sha256.txt"}
    require({p.name for p in assets.iterdir() if not p.name.startswith(".")} == asset_names, "Unexpected release asset count")
    expected = {name: path_record(assets / name) for name in sorted(asset_names)}
    (publication / "published-assets.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    (publication / "package-members.json").write_text(json.dumps(expected_members, indent=2) + "\n", encoding="utf-8")
    return expected


def verify_windows_package(archive, expected_members):
    with zipfile.ZipFile(archive) as zipped:
        require(len(zipped.namelist()) == len(expected_members) and set(zipped.namelist()) == set(expected_members), "Windows package member set differs")
        for name, expected in expected_members.items():
            info = zipped.getinfo(name)
            require(info.file_size == expected["bytes"] and not info.is_dir(), "Packaged member size differs: " + name)
            with zipped.open(name) as stream:
                require(hashlib.file_digest(stream, "sha256").hexdigest() == expected["sha256"], "Packaged member bytes differ: " + name)
        require(expected_members[EXE] == {"bytes": EXE_BYTES, "sha256": EXE_SHA}, "Packaged EXE differs from supplied build")
        require(len([name for name in zipped.namelist() if name.startswith("tree_profiles/") and name.endswith(".json")]) == 14, "Regional profiles are incomplete")


def require_source_refs(config, allow_tag_missing=False):
    require(api("git/ref/heads/main")["object"]["sha"] == config["expected_main_sha"], "main changed after source review")
    require(api("git/ref/tags/" + OLD_TAG)["object"]["sha"] == OLD_SOURCE, "Existing Beta 8.1 tag changed")
    tag = api("git/ref/tags/" + TAG, allow_missing=allow_tag_missing)
    if tag:
        require(tag["object"]["type"] == "commit" and tag["object"]["sha"] == config["source_sha"], "Beta 8.2 tag already points elsewhere")
    return tag


def prepare(config_path):
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY and os.environ["GITHUB_REF"] == "refs/heads/" + BRANCH, "Wrong publication environment")
    config = validate_config(json.loads(Path(config_path).read_text(encoding="utf-8")))
    trigger = os.environ["GITHUB_SHA"]
    require(git("rev-parse", "HEAD") == trigger, "Checkout does not match triggering commit")
    subprocess.run(["git", "merge-base", "--is-ancestor", CONTROL_BASE, trigger], check=True)
    changed = set(git("diff", "--name-only", CONTROL_BASE, trigger).splitlines())
    require(changed <= {WORKFLOW, SCRIPT, CONFIG}, "Unexpected control-branch changes: " + repr(sorted(changed)))
    require(not git("status", "--porcelain"), "Publication checkout is dirty")
    require_source_refs(config, allow_tag_missing=True)
    subprocess.run(["git", "merge-base", "--is-ancestor", PREPARED_SOURCE, config["source_sha"]], check=True)
    require(git("rev-parse", config["source_sha"] + "^{tree}") == config["source_tree_sha"], "Source tree differs from review")
    publication = Path("publication")
    require(not publication.exists(), "Preparation directory already exists")
    inputs = publication / "inputs"
    inputs.mkdir(parents=True)
    source_root = publication / "source"
    source_root.mkdir()
    source_files = source_tree(config["source_sha"], source_root)
    for name, expected in config["matching_source_files"].items():
        require(safe_name(name), "Unsafe matching source path")
        check(source_root / name, expected)
    for key in ("notes", "build_manifest", "uploaded_manifest", "build_validation", "windows_build_receipt"):
        require(safe_name(config[key]["name"]), "Unsafe evidence path")
        check(source_root / config[key]["name"], config[key])
    verify_supplied_manifest(source_root, config)
    executable = restore_executable(config["exe"], inputs)
    package_assets(source_root, publication, executable, config)
    receipt = {
        "config": config, "trigger": trigger, "source_files": source_files,
        "supplied_executable_unchanged": True,
        "all_142_supplied_source_and_support_file_hashes_match_archive": True,
        "original_windows_build_receipt_and_checksum_verified": True,
        "application_build_performed": False,
    }
    (publication / "source-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(config_path, publication / "transport-manifest.json")
    shutil.copyfile(SCRIPT, publication / "publish_beta82.py")
    git("update-ref", "refs/publication/beta82-source", config["source_sha"])
    git("bundle", "create", str(publication / "source.bundle"), "refs/publication/beta82-source", "^" + PREPARED_SOURCE)
    shutil.rmtree(inputs)
    print("Prepared unchanged Windows build and exact reviewed source:", config["source_sha"], flush=True)


def publication_state():
    publication = Path("publication")
    receipt = json.loads((publication / "source-manifest.json").read_text(encoding="utf-8"))
    config = validate_config(receipt["config"])
    expected = json.loads((publication / "published-assets.json").read_text(encoding="utf-8"))
    require(set(expected) == {EXE, PACKAGE, EXE + ".sha256.txt", PACKAGE + ".sha256.txt"}, "Unexpected recovery asset set")
    for name, info in expected.items():
        check(publication / "assets" / name, info)
    for name, info in receipt["source_files"].items():
        check(publication / "source" / name, info)
    return publication, receipt, config, expected


def find_release():
    matches = []
    for page in range(1, 101):
        releases = api("releases?per_page=100&page=" + str(page))
        matches.extend(release for release in releases if release["tag_name"] == TAG)
        if len(releases) < 100:
            break
    else:
        raise RuntimeError("Release listing exceeded safety bound")
    require(len(matches) <= 1, "Multiple releases use the Beta 8.2 tag")
    return matches[0] if matches else None


def validate_release(release, config, expected, complete):
    require(release["name"] == TITLE and release["tag_name"] == TAG and release["prerelease"] is True, "Existing release identity differs")
    require(release["target_commitish"] == config["source_sha"], "Existing release source differs")
    require(bytes_record(release["body"].encode("utf-8")) == {key: config["notes"][key] for key in ("bytes", "sha256")}, "Approved release notes differ")
    actual = {asset["name"]: asset for asset in release["assets"]}
    require(len(actual) == len(release["assets"]) and set(actual) <= set(expected), "Unexpected or duplicate release assets")
    if complete:
        require(set(actual) == set(expected), "Release assets are incomplete")
    for name, asset in actual.items():
        info = expected[name]
        require(asset["state"] == "uploaded" and asset["size"] == info["bytes"] and asset["digest"] == "sha256:" + info["sha256"], "Existing release asset differs: " + name)
    return actual


def publish():
    publication, receipt, config, expected = publication_state()
    tag = require_source_refs(config, allow_tag_missing=True)
    existing = find_release()
    if existing:
        validate_release(existing, config, expected, complete=not existing["draft"])
    if not tag:
        api("git/refs", method="POST", data={"ref": "refs/tags/" + TAG, "sha": config["source_sha"]})
    require_source_refs(config)
    if existing is None:
        existing = api("releases", method="POST", data={
            "tag_name": TAG, "target_commitish": config["source_sha"], "name": TITLE,
            "body": (publication / "source" / NOTES).read_bytes().decode("utf-8"),
            "draft": True, "prerelease": True, "make_latest": "false",
        })
    release_id = existing["id"]
    (publication / "release-id.json").write_text(json.dumps({"release_id": release_id}) + "\n", encoding="utf-8")
    actual = validate_release(existing, config, expected, complete=not existing["draft"])
    if existing["draft"]:
        for name in sorted(set(expected) - set(actual)):
            url = "https://uploads.github.com/repos/" + REPOSITORY + "/releases/" + str(release_id) + "/assets?" + urllib.parse.urlencode({"name": name})
            raw = subprocess.check_output([
                "gh", "api", "--method", "POST", "-H", "Content-Type: application/octet-stream",
                url, "--input", str(publication / "assets" / name),
            ])
            asset = json.loads(raw)
            info = expected[name]
            require(asset["name"] == name and asset["size"] == info["bytes"] and asset["digest"] == "sha256:" + info["sha256"], "Uploaded asset hash differs")
            print("Verified draft asset:", name, asset["size"], asset["digest"], flush=True)
        # Draft releases must be fetched by immutable ID, not by their public tag URL.
        draft = api("releases/" + str(release_id))
        validate_release(draft, config, expected, complete=True)
        require_source_refs(config)
        api("releases/" + str(release_id), method="PATCH", data={"draft": False, "prerelease": True, "make_latest": "false"})
    release = api("releases/" + str(release_id))
    validate_release(release, config, expected, complete=True)
    require(release["draft"] is False and release["published_at"], "Release remained a draft")
    print("Beta 8.2 prerelease is public:", release["html_url"], flush=True)


def check_archive_members(archive, source_files, kind):
    found = {}
    root_prefix = None
    if kind == "zip":
        context = zipfile.ZipFile(archive)
        entries = context.infolist()
        def entry_data(entry):
            return entry.filename, entry.is_dir(), ((entry.external_attr >> 16) & 0o170000) == 0o120000, context.open(entry)
    else:
        context = tarfile.open(archive, "r:gz")
        entries = context.getmembers()
        def entry_data(entry):
            return entry.name, entry.isdir(), not (entry.isdir() or entry.isfile()), context.extractfile(entry) if entry.isfile() else None
    try:
        for entry in entries:
            name, is_dir, unsafe, stream = entry_data(entry)
            require(safe_name(name) and not unsafe, "Unsafe automatic source archive member")
            pieces = PurePosixPath(name).parts
            if root_prefix is None:
                root_prefix = pieces[0]
            require(pieces[0] == root_prefix, "Automatic source archive has multiple roots")
            if is_dir:
                if stream is not None:
                    stream.close()
                continue
            require(len(pieces) > 1, "Automatic source archive file lacks repository prefix")
            relative = "/".join(pieces[1:])
            require(relative not in found and relative in source_files, "Unexpected automatic source file: " + relative)
            expected = source_files[relative]
            checksum = hashlib.sha256()
            size = 0
            with stream:
                while True:
                    raw = stream.read(1024 * 1024)
                    if not raw:
                        break
                    checksum.update(raw)
                    size += len(raw)
            require(size == expected["bytes"] and checksum.hexdigest() == expected["sha256"], "Automatic source bytes differ: " + relative)
            found[relative] = True
    finally:
        context.close()
    require(set(found) == set(source_files), "Automatic source archive omitted committed files")
    return len(found)


def verify_downloads():
    publication, receipt, config, expected = publication_state()
    release_id = json.loads((publication / "release-id.json").read_text())["release_id"]
    release = api("releases/" + str(release_id))
    actual = validate_release(release, config, expected, complete=True)
    require(release["draft"] is False and release["published_at"], "Release is not public")
    require_source_refs(config)
    downloaded = publication / "public-downloads"
    downloaded.mkdir(parents=True, exist_ok=True)
    prefix = "https://github.com/" + REPOSITORY + "/releases/download/" + TAG + "/"
    def download(name):
        require(actual[name]["browser_download_url"] == prefix + name, "Unexpected public asset URL")
        record = public_download(actual[name]["browser_download_url"], downloaded / name, expected[name])
        print("Verified unauthenticated public download:", name, record["bytes"], record["sha256"], flush=True)
        return name
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        require(set(pool.map(download, sorted(expected))) == set(expected), "Incomplete public download verification")
    for name in (EXE, PACKAGE):
        require((downloaded / (name + ".sha256.txt")).read_text(encoding="ascii") == expected[name]["sha256"] + "  " + name + "\n", "Public checksum file content differs")
    expected_members = json.loads((publication / "package-members.json").read_text())
    verify_windows_package(downloaded / PACKAGE, expected_members)
    archives = {}
    for kind, suffix in (("zip", ".zip"), ("tar", ".tar.gz")):
        url = "https://github.com/" + REPOSITORY + "/archive/refs/tags/" + TAG + suffix
        target = downloaded / ("source" + suffix)
        measured = public_download(url, target)
        count = check_archive_members(target, receipt["source_files"], kind)
        archives[kind] = {**measured, "url": url, "verified_committed_files": count}
        print("Verified unauthenticated automatic source archive:", kind, count, "exact source files", flush=True)
    require_source_refs(config)
    validate_release(api("releases/" + str(release_id)), config, expected, complete=True)
    report = {
        "release_url": release["html_url"], "release_id": release_id, "tag": TAG,
        "source_sha": config["source_sha"], "source_tree_sha": config["source_tree_sha"],
        "publication_workflow": "https://github.com/" + REPOSITORY + "/actions/runs/" + os.environ["GITHUB_RUN_ID"],
        "actual_public_downloads_verified_without_authentication": True,
        "zip_executable_matches_supplied_build": True,
        "all_package_support_files_verified": True,
        "source_archives_match_release_commit": True,
        "executable_rebuilt_or_modified": False,
        "windows_application_or_game_testing_performed_by_publication_workflow": False,
        "assets": {name: {**info, "id": actual[name]["id"], "url": actual[name]["browser_download_url"]} for name, info in expected.items()},
        "automatic_source_archives": archives,
        "package_members": expected_members,
    }
    (publication / "verified-release.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("## Beta 8.2 publication verified\n\n" + release["html_url"] + "\n\nSource: `" + config["source_sha"] + "`\n\nAll four public assets were downloaded without authentication and matched their measured sizes and SHA-256 hashes. The packaged executable equals the supplied build. All packaged support files and both automatic source archives were checked against the immutable release source.\n\nNo application build, binary edits, Windows application testing, or in-game testing were performed by this publication workflow.\n")
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "publish", "verify-downloads"))
    parser.add_argument("--transport", default=CONFIG)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.transport)
    elif args.operation == "publish":
        publish()
    else:
        verify_downloads()


if __name__ == "__main__":
    main()
