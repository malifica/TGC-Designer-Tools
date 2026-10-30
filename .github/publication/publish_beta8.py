#!/usr/bin/env python3
"""Publish the supplied Beta 8 executable and matching source without rebuilding."""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
import zlib


REPOSITORY = "malifica/TGC-Designer-Tools"
BRANCH = "release/beta8-publication"
BASE_MAIN = "df4c2cf0346273774555a34458f2416a3f32fb5e"
PUBLICATION_BASE = "6491bdffa1cc6bc1b5f0d2647c99b29093a44685"
TAG = "v0.5.0-2k25-beta8"
TITLE = "TGC Designer Tools 2K25 - Beta 8"
EXE = "tgc_gui_2k25_beta8.exe"
PACKAGE = "TGC-Designer-Tools-2K25-v0.5.0-2k25-beta8-Windows-x64.zip"
NOTES = "RELEASE_NOTES_v0.5.0-2k25-beta8.md"
MANIFEST = "UPLOAD_MANIFEST.json"
MANIFEST_SHA = "7095efe44434809fefb6ec44b6cb779e7d2fa0bd82b3d774410209c965f3342b"
NOTES_SHA = "74196a427d57e400ee05388b205e313ce29f5344aa89aabbd36588b53592431a"
EXE_SHA = "c09217ae1b167e7c9fd232cde24c11b5206944f795de964ad9107510861b3d81"
EXE_BYTES = 194206055
BASE_EXE = "tgc_gui_2k25_beta7.exe"
BASE_EXE_BYTES = 153776639
BASE_EXE_SHA = "f00c4a50beaa09406e76a2cde04722557f1b118a03836aff33395ef72b3bdd72"
WORKFLOW = ".github/workflows/publish-existing-beta8.yml"
SCRIPT = ".github/publication/publish_beta8.py"
TRANSPORT = ".github/publication/beta8-transport.json"
REFERENCE_WORKFLOWS = {
    ".github/workflows/beta8-byte-reference.yml",
    ".github/workflows/beta8-final-transfer-references.yml",
    ".github/workflows/beta8-transfer-codec.yml",
    ".github/workflows/beta8-transfer-reference.yml",
}
TEMPORARY = REFERENCE_WORKFLOWS | {WORKFLOW, SCRIPT, TRANSPORT}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check(path, expected):
    path = Path(path)
    require(path.stat().st_size == expected["bytes"], f"Size mismatch: {path.name}")
    require(digest(path) == expected["sha256"], f"SHA-256 mismatch: {path.name}")


def git(*arguments, binary=False, env=None):
    return subprocess.check_output(["git", *arguments], env=env, text=not binary).strip() if not binary else subprocess.check_output(["git", *arguments], env=env)


def api(path, method="GET", data=None, allow_missing=False):
    headers = {"Accept": "application/vnd.github+json", "Authorization": "Bearer " + os.environ["GH_TOKEN"], "X-GitHub-Api-Version": "2022-11-28"}
    body = None if data is None else json.dumps(data).encode("utf-8")
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + "/" + path, data=body, headers=headers, method=method)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_missing:
                return None
            if method != "GET" or error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("GitHub request did not finish")


def fetch_blob(entry):
    sha = entry["git_blob_sha"]
    require(len(sha) == 40 and all(c in "0123456789abcdef" for c in sha), "Invalid Git blob SHA")
    obj = api("git/blobs/" + sha)
    require(obj["encoding"] == "base64", "Unexpected Git blob encoding")
    raw = base64.b64decode(obj["content"])
    actual = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
    require(actual == sha, "Git blob object checksum mismatch")
    require(len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"], "Transport chunk checksum mismatch")
    return raw


def assemble(record, folder):
    name = record["name"]
    require(PurePosixPath(name).name == name and name not in ("", ".", ".."), "Invalid transport filename")
    output = folder / name
    chunks = record["chunks"]
    require(chunks and sum(c["bytes"] for c in chunks) == record["bytes"], "Invalid transport chunk sizes")
    # Bounded batches preserve chunk order without accumulating the full EXE in memory.
    with output.open("wb") as stream, concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for offset in range(0, len(chunks), 8):
            for raw in pool.map(fetch_blob, chunks[offset:offset + 8]):
                stream.write(raw)
    check(output, record)
    print("Verified supplied file:", name, record["bytes"], record["sha256"], flush=True)
    return output


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts and ".git" not in path.parts


def download_recipe_artifacts(recipe, folder):
    directories = {}
    for reference in recipe["artifacts"]:
        key = reference["id"]
        require(key not in directories and key.isidentifier(), "Invalid artifact identifier")
        metadata = api("actions/artifacts/" + str(reference["artifact_id"]))
        require(metadata["id"] == reference["artifact_id"] and metadata["name"] == reference["name"] and metadata["workflow_run"]["id"] == reference["run_id"] and not metadata["expired"], "Retained reference artifact changed or expired")
        directory = folder / "reference-artifacts" / key
        directory.mkdir(parents=True, exist_ok=True)
        subprocess.run(["gh", "run", "download", str(reference["run_id"]), "--repo", REPOSITORY, "--name", reference["name"], "--dir", str(directory)], check=True)
        directories[key] = directory
    return directories


def materialize_recipe_sources(recipe, folder):
    directories = download_recipe_artifacts(recipe, folder)
    prepared = {}
    cache = folder / "reference-sources"
    cache.mkdir()
    for source in recipe["sources"]:
        key = source["id"]
        require(key.isidentifier() and key != "literal" and key not in prepared, "Invalid source identifier")
        require(source["artifact"] in directories and source["members"], "Unknown source artifact")
        require(all(safe_name(member) for member in source["members"]), "Invalid artifact member path")
        first, *nested = source["members"]
        artifact_file = directories[source["artifact"]] / first
        if nested:
            with zipfile.ZipFile(artifact_file) as zipped:
                data = zipped.read(nested[0])
            for member in nested[1:]:
                with zipfile.ZipFile(io.BytesIO(data)) as zipped:
                    data = zipped.read(member)
        else:
            data = artifact_file.read_bytes()
        transform = source.get("transform")
        if transform:
            require(transform["kind"] == "zlib" and type(transform["level"]) is int and 0 <= transform["level"] <= 9, "Unsupported byte transform")
            data = zlib.compress(data, transform["level"])
        require(len(data) == source["bytes"] and hashlib.sha256(data).hexdigest() == source["sha256"], "Reference bytes differ: " + key)
        destination = cache / (key + ".bin")
        destination.write_bytes(data)
        prepared[key] = destination
    print("Verified exact byte references:", len(prepared), flush=True)
    return prepared


def restore_executable(record, folder):
    if "chunks" in record:
        return assemble(record, folder)
    require(record.get("method") in ("copy-recipe", "copy-recipe-v1"), "Unsupported executable transport")
    recipe_path = assemble(record["recipe"], folder)
    recipe = json.loads(recipe_path.read_text())
    require(recipe["format"] in ("tgc-exact-byte-transfer-v1", "tgc-exact-byte-transfer-v2"), "Unsupported copy recipe")
    require(recipe["target"] == {"name": EXE, "bytes": EXE_BYTES, "sha256": EXE_SHA}, "Copy recipe target changed")
    literals = assemble(record["literal"], folder)
    require(all(record["literal"][key] == recipe["literal"][key] for key in ("name", "bytes", "sha256")), "Copy recipe literal payload changed")
    if recipe["format"] == "tgc-exact-byte-transfer-v1":
        base_url = "https://github.com/" + REPOSITORY + "/releases/download/v0.5.0-2k25-beta7/" + BASE_EXE
        require(recipe["base"] == {"url": base_url, "bytes": BASE_EXE_BYTES, "sha256": BASE_EXE_SHA}, "Copy recipe base changed")
        subprocess.run(["gh", "release", "download", "v0.5.0-2k25-beta7", "--repo", REPOSITORY, "--pattern", BASE_EXE, "--dir", str(folder), "--clobber"], check=True)
        base = folder / BASE_EXE
        check(base, recipe["base"])
        source_paths = {"copy": base}
        segments = [{"source": segment["kind"], "offset": segment["offset"], "length": segment["length"]} for segment in recipe["segments"]]
    else:
        source_paths = materialize_recipe_sources(recipe, folder)
        segments = recipe["segments"]
    source_paths["literal"] = literals
    require(sum(segment["length"] for segment in segments) == EXE_BYTES, "Copy recipe target length mismatch")
    output = folder / EXE
    sources = {key: (path.open("rb"), path.stat().st_size) for key, path in source_paths.items()}
    try:
        with output.open("wb") as destination:
            for segment in segments:
                require(segment["source"] in sources, "Invalid copy recipe source")
                stream, size = sources[segment["source"]]
                offset, length = segment["offset"], segment["length"]
                require(type(offset) is int and type(length) is int and offset >= 0 and length > 0 and offset + length <= size, "Copy recipe segment exceeds its source")
                stream.seek(offset)
                remaining = length
                while remaining:
                    raw = stream.read(min(remaining, 1024 * 1024))
                    require(raw, "Unexpected end of copy recipe source")
                    destination.write(raw)
                    remaining -= len(raw)
    finally:
        for stream, _ in sources.values():
            stream.close()
    check(output, {"bytes": EXE_BYTES, "sha256": EXE_SHA})
    print("Restored and verified the supplied executable byte for byte:", EXE_SHA, flush=True)
    return output


def source_payload(archive, destination, executable):
    with zipfile.ZipFile(archive) as zipped:
        names = zipped.namelist()
        require(len(names) == len(set(names)), "Duplicate source ZIP members")
        require(MANIFEST in names, "Original source manifest is missing")
        manifest_bytes = zipped.read(MANIFEST)
        require(hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA, "Original source manifest changed")
        manifest = json.loads(manifest_bytes)
        require(manifest["version"] == 1 and len(manifest["files"]) == 138, "Unexpected source manifest")
        exe_path = manifest["exe"]
        require(exe_path == "dist/" + EXE, "Unexpected executable path")
        require(manifest["files"][exe_path] == {"bytes": EXE_BYTES, "sha256": EXE_SHA}, "Executable provenance changed")
        check(executable, manifest["files"][exe_path])
        source_names = set(manifest["files"]) - {exe_path}
        require(set(names) == source_names | {MANIFEST}, "Source ZIP must contain exactly the original source files and manifest, excluding EXE")
        for name in sorted(source_names):
            member = PurePosixPath(name)
            require(not member.is_absolute() and ".." not in member.parts and ".git" not in member.parts, "Unsafe source member")
            info = zipped.getinfo(name)
            require(not info.is_dir() and ((info.external_attr >> 16) & 0o170000) != 0o120000, "Unsupported source ZIP member")
            raw = zipped.read(name)
            expected = manifest["files"][name]
            require(len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"], "Source file changed: " + name)
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        (destination / "BETA8_BUILD_SOURCE_MANIFEST.json").write_bytes(manifest_bytes)
    return manifest, source_names


def update_documentation(root):
    notes = (root / NOTES).read_bytes()
    require(hashlib.sha256(notes).hexdigest() == NOTES_SHA, "Approved release notes changed")
    notes_text = notes.decode("utf-8")
    highlights = notes_text.split("## Highlights\n\n", 1)[1].split("\n\n## Using Beta 8", 1)[0]
    readme = root / "README.md"
    old = readme.read_text(encoding="utf-8-sig")
    require(old.startswith("# TGC Designer Tools") and "## Beta 7 highlights\n\n" in old, "Unexpected README format")
    before_highlights, remaining = old.split("## Beta 7 highlights\n\n", 1)
    _, next_heading, remainder = remaining.partition("\n## ")
    require(next_heading, "Missing README section after highlights")
    new = before_highlights + "## Beta 8 highlights\n\n" + highlights + "\n" + next_heading + remainder
    new = new.replace("from **LiDAR, GeoTIFF DEMs, and OpenStreetMap**.", "from **LiDAR, GeoTIFF DEMs, OpenStreetMap, and Unity RAW/SVG data**.", 1)
    new = new.replace("**Current release: v0.5.0-2k25-beta7**", "**Current release: " + TAG + "**", 1)
    new = new.replace("[Download Beta 7](https://github.com/" + REPOSITORY + "/releases/tag/v0.5.0-2k25-beta7)", "[Download Beta 8](https://github.com/" + REPOSITORY + "/releases/tag/" + TAG + ")", 1)
    new = new.replace("[Release notes](RELEASE_NOTES_v0.5.0-2k25-beta7.md)", "[Release notes](" + NOTES + ")", 1)
    new = new.replace("tgc_gui_2k25_beta7.exe", EXE).replace("TGC Designer Tools 2K25 - Beta 7", TITLE).replace("BUILD_TGC_2K25_BETA7.bat", "BUILD_TGC_2K25_BETA8.bat")
    new = new.replace("Beta 6 remains available separately.", "Beta 7 remains available separately.")
    unrelated = "The main application creates the course. **Course Finisher, Course Architect, and Adaptive Terrain Converter remain separate tools** and are not updated by this release.\n\n"
    require(unrelated in new, "Expected README scope paragraph missing")
    new = new.replace(unrelated, "")
    readme.write_text(new, encoding="utf-8", newline="\n")
    changelog = root / "CHANGELOG.md"
    old = changelog.read_text(encoding="utf-8-sig")
    title, newline, body = old.partition("\n")
    require(newline and title.startswith("#"), "Unexpected CHANGELOG format")
    changelog.write_text(title + "\n\n## " + TAG + "\n\n" + highlights + "\n\n" + body.lstrip("\n"), encoding="utf-8", newline="\n")
    build_doc = root / "BUILD_WINDOWS.md"
    old = build_doc.read_text(encoding="utf-8-sig")
    title, newline, body = old.partition("\n")
    require(newline and title.startswith("#"), "Unexpected build documentation format")
    require(body.lstrip("\n").startswith("## Current release: Beta 7\n"), "Unexpected current build documentation")
    _, next_heading, remaining = body.lstrip("\n").partition("\n## ")
    require(next_heading, "Missing historical build documentation")
    section = "## Current source: Beta 8\n\nThe Beta 8 release contains the existing Windows executable supplied with its matching source. The source includes `BUILD_TGC_2K25_BETA8.bat` and `BUILD_TGC_2K25_BETA8.py` for development. The older commands below describe previous release environments.\n"
    build_doc.write_text(title + "\n\n" + section + next_heading + remaining, encoding="utf-8", newline="\n")
    return {"README.md", "CHANGELOG.md", "BUILD_WINDOWS.md", NOTES, "BETA8_BUILD_SOURCE_MANIFEST.json"}


def package_assets(root, publication, executable, source_names):
    assets = publication / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    target_exe = assets / EXE
    shutil.copyfile(executable, target_exe)
    check(target_exe, {"bytes": EXE_BYTES, "sha256": EXE_SHA})
    members = {EXE: target_exe, NOTES: root / NOTES, "LICENSE": root / "LICENSE", "laszip/LICENSE.txt": root / "laszip/LICENSE.txt", "splines.json": root / "extras/splines.json"}
    for name in sorted(source_names):
        if name.startswith("tree_profiles/"):
            members[name] = root / name
    archive = assets / PACKAGE
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zipped:
        for name, path in sorted(members.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 30, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            with path.open("rb") as source, zipped.open(info, "w", force_zip64=True) as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    with zipfile.ZipFile(archive) as zipped:
        require(set(zipped.namelist()) == set(members), "Packaged member set changed")
        with zipped.open(EXE) as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == EXE_SHA, "Packaged EXE bytes changed")
        require(zipped.read(NOTES) == (root / NOTES).read_bytes(), "Packaged release notes changed")
        require(len([name for name in zipped.namelist() if name.startswith("tree_profiles/") and name.endswith(".json")]) == 14, "Regional profiles missing")
    for asset in (target_exe, archive):
        (assets / (asset.name + ".sha256.txt")).write_text(digest(asset) + "  " + asset.name + "\n", encoding="ascii", newline="\n")
    asset_names = {EXE, PACKAGE, EXE + ".sha256.txt", PACKAGE + ".sha256.txt"}
    require({p.name for p in assets.iterdir() if not p.name.startswith(".")} == asset_names, "Unexpected release asset count")
    expected = {name: {"bytes": (assets / name).stat().st_size, "sha256": digest(assets / name)} for name in sorted(asset_names)}
    (publication / "published-assets.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")
    return expected


def prepare(transport_path):
    root = Path.cwd()
    require(os.environ["GITHUB_REPOSITORY"] == REPOSITORY, "Wrong repository")
    trigger = os.environ["GITHUB_SHA"]
    require(git("rev-parse", "HEAD") == trigger, "Checkout does not match triggering commit")
    subprocess.run(["git", "merge-base", "--is-ancestor", PUBLICATION_BASE, trigger], check=True)
    changed = set(git("diff", "--name-only", PUBLICATION_BASE, trigger).splitlines())
    require(changed <= {WORKFLOW, SCRIPT, TRANSPORT}, "Unexpected publication-branch changes: " + repr(sorted(changed)))
    require(git("diff", "--name-only") == "" and git("diff", "--cached", "--name-only") == "", "Dirty checkout")
    transport = json.loads(Path(transport_path).read_text())
    require(transport["version"] == 1, "Unsupported transport manifest")
    require(transport["repository"] == REPOSITORY and transport["branch"] == BRANCH, "Wrong transport target")
    require(transport["expected_main_sha"] == BASE_MAIN and transport["publication_base_sha"] == PUBLICATION_BASE and transport["tag"] == TAG, "Wrong transport base")
    require(transport["exe"]["name"] == EXE and transport["exe"]["bytes"] == EXE_BYTES and transport["exe"]["sha256"] == EXE_SHA, "Wrong supplied executable")
    publication = root / "publication"
    inputs = publication / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    executable = restore_executable(transport["exe"], inputs)
    archive = assemble(transport["source"], inputs)
    tracked = set(git("ls-files").splitlines())
    before = {name: digest(root / name) for name in tracked if name not in TEMPORARY}
    manifest, source_names = source_payload(archive, root, executable)
    docs = update_documentation(root)
    allowed = source_names | docs
    for name, sha in before.items():
        if name not in allowed:
            require(digest(root / name) == sha, "Unrelated tracked file changed: " + name)
    package_assets(root, publication, executable, source_names)
    saved_source = publication / "source"
    for name in sorted(allowed):
        destination = saved_source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
        original = git("ls-files", "-s", "--", name)
        mode = original.split()[0] if original else "100644"
        require(mode in ("100644", "100755"), "Unsupported source mode")
        sha = git("hash-object", "-w", "--no-filters", name)
        git("update-index", "--add", "--cacheinfo", mode, sha, name)
    for name in sorted(TEMPORARY):
        git("update-index", "--force-remove", name)
    staged = set(git("diff", "--cached", "--name-only", BASE_MAIN).splitlines())
    require(staged <= allowed, "Unrelated files would change in main: " + repr(sorted(staged - allowed)))
    for name in source_names:
        require(hashlib.sha256(git("show", ":" + name, binary=True)).hexdigest() == manifest["files"][name]["sha256"], "Staged source differs: " + name)
    after = {name: digest(root / name) for name in allowed}
    source_manifest = {"base": BASE_MAIN, "trigger": trigger, "original_manifest_sha256": MANIFEST_SHA, "before": before, "after": after, "original_executable": {"bytes": EXE_BYTES, "sha256": EXE_SHA}, "removed_temporary_paths": sorted(TEMPORARY)}
    tree = git("write-tree")
    timestamp = git("show", "-s", "--format=%cI", trigger)
    env = dict(os.environ, GIT_AUTHOR_NAME="github-actions[bot]", GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com", GIT_COMMITTER_NAME="github-actions[bot]", GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com", GIT_AUTHOR_DATE=timestamp, GIT_COMMITTER_DATE=timestamp)
    final_sha = git("commit-tree", tree, "-p", trigger, "-m", "Release Beta 8 from the supplied Windows build and matching source", env=env)
    source_manifest["final_sha"] = final_sha
    source_manifest["tree"] = tree
    (publication / "source-manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(transport_path, publication / "transport-manifest.json")
    shutil.copyfile(root / SCRIPT, publication / "publish_beta8.py")
    git("update-ref", "refs/publication/beta8", final_sha)
    git("bundle", "create", str(publication / "source.bundle"), "refs/publication/beta8", "^" + BASE_MAIN)
    # Raw input chunks are reproducible and would double the retained artifact size.
    shutil.rmtree(inputs)
    print("Prepared exact existing build and matching source:", final_sha, flush=True)


def publication_state():
    publication = Path("publication")
    source = json.loads((publication / "source-manifest.json").read_text())
    expected = json.loads((publication / "published-assets.json").read_text())
    require(source["base"] == BASE_MAIN and source["original_manifest_sha256"] == MANIFEST_SHA, "Recovery source provenance changed")
    for name, info in expected.items():
        check(publication / "assets" / name, info)
    for name, sha in source["after"].items():
        require(digest(publication / "source" / name) == sha, "Recovery source changed: " + name)
    return publication, source, expected


def validate_release(release, source, expected, complete):
    require(release["name"] == TITLE and release["tag_name"] == TAG and release["prerelease"], "Existing release metadata differs")
    require(release["body"].strip() == (Path("publication/source") / NOTES).read_text().strip(), "Existing release notes differ")
    require(release["target_commitish"] in (source["final_sha"], BRANCH, "main"), "Existing release points elsewhere")
    actual = {asset["name"]: asset for asset in release["assets"]}
    require(set(actual) <= set(expected), "Release contains unexpected assets")
    if complete:
        require(set(actual) == set(expected), "Release assets are incomplete")
    for name, asset in actual.items():
        info = expected[name]
        require(asset["state"] == "uploaded" and asset["size"] == info["bytes"] and asset["digest"] == "sha256:" + info["sha256"], "Existing release asset differs: " + name)
    return actual


def publish():
    publication, source, expected = publication_state()
    final_sha = source["final_sha"]
    trigger = source["trigger"]
    refs = {label: api("git/ref/" + path, allow_missing=True) for label, path in {"main": "heads/main", "branch": "heads/" + BRANCH, "tag": "tags/" + TAG}.items()}
    main_sha = refs["main"]["object"]["sha"]
    branch_sha = refs["branch"]["object"]["sha"]
    tag_sha = refs["tag"]["object"]["sha"] if refs["tag"] else None
    require(main_sha in (BASE_MAIN, final_sha), "main advanced unexpectedly")
    require(branch_sha in (trigger, final_sha), "Publication branch advanced unexpectedly")
    require(tag_sha in (None, final_sha), "Beta 8 tag already points elsewhere")
    require(api("git/ref/tags/v0.5.0-2k25-beta7")["object"]["sha"] == BASE_MAIN, "Beta 7 tag changed")
    existing = api("releases/tags/" + TAG, allow_missing=True)
    if existing:
        validate_release(existing, source, expected, complete=not existing["draft"])
    if main_sha != final_sha or branch_sha != final_sha or tag_sha != final_sha:
        git("push", "--atomic", "origin", final_sha + ":refs/heads/main", final_sha + ":refs/heads/" + BRANCH, final_sha + ":refs/tags/" + TAG)
    for path in ("heads/main", "heads/" + BRANCH, "tags/" + TAG):
        require(api("git/ref/" + path)["object"]["sha"] == final_sha, "Published ref does not match: " + path)
    if not existing:
        existing = api("releases", method="POST", data={"tag_name": TAG, "target_commitish": final_sha, "name": TITLE, "body": (publication / "source" / NOTES).read_text(), "draft": True, "prerelease": True, "make_latest": "false"})
    actual = validate_release(existing, source, expected, complete=not existing["draft"])
    if existing["draft"]:
        for name in sorted(set(expected) - set(actual)):
            subprocess.run(["gh", "release", "upload", TAG, str(publication / "assets" / name), "--repo", REPOSITORY], check=True)
        draft = api("releases/tags/" + TAG)
        validate_release(draft, source, expected, complete=True)
        api("releases/" + str(draft["id"]), method="PATCH", data={"draft": False, "prerelease": True, "make_latest": "false"})
    release = api("releases/tags/" + TAG)
    validate_release(release, source, expected, complete=True)
    require(not release["draft"], "Release remained a draft")
    print("Beta 8 prerelease is public:", release["html_url"], flush=True)


def verify_downloads():
    publication, source, expected = publication_state()
    release = api("releases/tags/" + TAG)
    actual = validate_release(release, source, expected, complete=True)
    require(not release["draft"], "Release is not public")
    downloaded = publication / "download-verification"
    downloaded.mkdir(parents=True, exist_ok=True)
    subprocess.run(["gh", "release", "download", TAG, "--repo", REPOSITORY, "--dir", str(downloaded), "--pattern", "*", "--clobber"], check=True)
    require({p.name for p in downloaded.iterdir() if not p.name.startswith(".")} == set(expected), "Unexpected downloaded assets")
    for name, info in expected.items():
        check(downloaded / name, info)
    for name in (EXE, PACKAGE):
        require((downloaded / (name + ".sha256.txt")).read_text(encoding="ascii") == digest(downloaded / name) + "  " + name + "\n", "Downloaded checksum text is wrong")
    with zipfile.ZipFile(downloaded / PACKAGE) as zipped:
        with zipped.open(EXE) as stream:
            require(hashlib.file_digest(stream, "sha256").hexdigest() == EXE_SHA, "Downloaded ZIP executable differs from the supplied build")
        require(zipped.read(NOTES) == (publication / "source" / NOTES).read_bytes(), "Downloaded ZIP release notes differ")
    for path in ("heads/main", "heads/" + BRANCH, "tags/" + TAG):
        require(api("git/ref/" + path)["object"]["sha"] == source["final_sha"], "Published source reference changed")
    report = {"release_url": release["html_url"], "source_sha": source["final_sha"], "exe_sha256": EXE_SHA, "actual_release_downloads_verified": True, "zip_executable_matches_supplied_build": True, "assets": {name: {**info, "url": actual[name]["browser_download_url"]} for name, info in expected.items()}}
    (publication / "verified-release.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("## Beta 8 publication verified\n\n" + release["html_url"] + "\n\nSource: `" + source["final_sha"] + "`\n\nAll four actual release downloads match their expected SHA-256 hashes. The executable inside the Windows ZIP matches the supplied build.\n\nExecutable SHA-256: `" + EXE_SHA + "`\n")
    print(json.dumps(report, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "publish", "verify-downloads"))
    parser.add_argument("--transport", default=TRANSPORT)
    args = parser.parse_args()
    if args.operation == "prepare":
        prepare(args.transport)
    elif args.operation == "publish":
        publish()
    else:
        verify_downloads()


if __name__ == "__main__":
    main()
