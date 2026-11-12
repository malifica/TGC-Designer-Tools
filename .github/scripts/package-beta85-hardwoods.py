"""Package the checked Beta 8.5 hardwood build without rebuilding the EXE."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[2]
EXE_NAME = "tgc_gui_2k25_beta8_5.exe"
PROFILE_ID = "american_hardwoods_summer"
EXPECTED_THEME_COUNT = 26
PORTABLE_ZIP = "TGC_Beta8_5_American_Hardwoods_Summer_Windows_x64.zip"
THEME_ZIP = "American_Hardwoods_Summer_Theme.zip"
README_NAME = "README_AMERICAN_HARDWOODS.txt"


def record(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), "Expected a JSON object: " + str(path))
    return value


def checksums(files: dict[str, Path]) -> str:
    return "".join(record(path)["sha256"] + "  " + name + "\n"
                   for name, path in sorted(files.items()))


def write_checked_zip(destination: Path, files: dict[str, Path]) -> None:
    """Use explicit members and check the final archive before exposing it."""
    temporary = destination.with_suffix(".zip.tmp")
    manifest = checksums(files).encode("ascii")
    expected = {name: record(path) for name, path in files.items()}
    try:
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED,
                             compresslevel=6, allowZip64=True) as archive:
            for name, path in sorted(files.items()):
                require(not name.startswith(("/", "\\")) and ".." not in Path(name).parts,
                        "Unsafe archive member: " + name)
                archive.write(path, name)
            archive.writestr("SHA256SUMS.txt", manifest)
        with zipfile.ZipFile(temporary) as archive:
            require(set(archive.namelist()) == set(files) | {"SHA256SUMS.txt"}
                    and len(archive.namelist()) == len(files) + 1,
                    "Archive members differ from the explicit package list.")
            require(archive.read("SHA256SUMS.txt") == manifest,
                    "The archive checksum list changed.")
            for name, expected_record in expected.items():
                digest = hashlib.sha256()
                size = 0
                with archive.open(name) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b""):
                        size += len(block)
                        digest.update(block)
                require({"bytes": size, "sha256": digest.hexdigest()} == expected_record,
                        "Packaged member differs from the checked input: " + name)
                require(record(files[name]) == expected_record,
                        "Input changed while packaging: " + name)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> None:
    exe = ROOT / "dist" / EXE_NAME
    checksum_path = exe.with_name(EXE_NAME + ".sha256.txt")
    receipt_path = exe.with_name(EXE_NAME + ".build.json")
    profile_relative = "tree_profiles/" + PROFILE_ID + ".json"
    catalog_relative = "tree_profiles/filter_ready/" + PROFILE_ID + ".json"
    profile_path = ROOT / profile_relative
    catalog_path = ROOT / catalog_relative
    readme = ROOT / README_NAME
    license_path = ROOT / "LICENSE"
    for path in (exe, checksum_path, receipt_path, profile_path, catalog_path, readme, license_path):
        require(path.is_file() and not path.is_symlink(), "Required package input is missing: " + str(path))

    # The standard builder has already completed the native Windows and frozen
    # runtime checks. Bind these packages to that exact checked output.
    binary = record(exe)
    require(checksum_path.read_text(encoding="ascii") == binary["sha256"] + "  " + EXE_NAME + "\n",
            "EXE checksum sidecar does not match the built executable.")
    receipt = read_json(receipt_path)
    require(receipt.get("schema") == "tgc-windows-build-inputs-v1"
            and receipt.get("release") == "v0.5.0-2k25-beta8.5"
            and receipt.get("exe") == dict(path="dist/" + EXE_NAME, **binary),
            "Windows build receipt does not match the built executable.")
    for relative in (profile_relative, catalog_relative):
        require(receipt.get("source_and_support", {}).get(relative) == record(ROOT / relative),
                "Theme file differs from the checked build receipt: " + relative)

    profile = read_json(profile_path)
    catalog = read_json(catalog_path)
    require(profile.get("id") == PROFILE_ID and profile.get("enabled") is True,
            "American Hardwoods profile is disabled or has the wrong identity.")
    require(catalog.get("profile_id") == PROFILE_ID and catalog.get("complete") is True,
            "American Hardwoods Filter Ready catalog is incomplete or mismatched.")

    matches = []
    for path in (ROOT / "build").glob(EXE_NAME[:-4] + "_release_build_*/THEME_PORTABILITY_REPORT.json"):
        report = read_json(path)
        if report.get("status") == "PASS" and report.get("exe_sha256") == binary["sha256"]:
            matches.append((path, report))
    require(len(matches) == 1, "Expected exactly one passing portability report for this EXE.")
    portability_path, portability = matches[0]
    factory = portability.get("factory_profiles", {})
    require(len(factory) == EXPECTED_THEME_COUNT
            and portability.get("archive", {}).get("factory_profile_count") == EXPECTED_THEME_COUNT,
            "The EXE-only report does not verify all 26 factory themes.")
    require(factory.get(PROFILE_ID, {}).get("display_name") == profile.get("display_name"),
            "The new theme is missing from the EXE-only factory verification.")
    require(portability.get("no_external_theme_directory_supplied") is True,
            "The build has no verified EXE-only theme portability result.")
    for relative in (profile_relative, catalog_relative):
        require(portability.get("source_json", {}).get(relative) == record(ROOT / relative),
                "Embedded theme data differs from the package input: " + relative)
    require(any(check.get("flag") == "--verify-filter-ready"
                and check.get("exit_code") == 0
                and check.get("runtime_catalog_count") == EXPECTED_THEME_COUNT
                and check.get("all_factory_names_and_counts_verified") is True
                for check in portability.get("checks", [])),
            "The copied EXE did not verify every installed Filter Ready catalog.")

    output = ROOT / "dist" / "hardwoods_release"
    output.mkdir(parents=True, exist_ok=True)
    portable_zip = output / PORTABLE_ZIP
    theme_zip = output / THEME_ZIP
    write_checked_zip(portable_zip, {
        EXE_NAME: exe,
        EXE_NAME + ".build.json": receipt_path,
        README_NAME: readme,
        "LICENSE": license_path,
    })
    write_checked_zip(theme_zip, {
        profile_relative: profile_path,
        catalog_relative: catalog_path,
        README_NAME: readme,
        "LICENSE": license_path,
    })
    saved_portability = output / "THEME_PORTABILITY_REPORT.json"
    shutil.copy2(portability_path, saved_portability)
    build_report = {
        "schema": "tgc-beta85-american-hardwoods-build-v1",
        "status": "PASS",
        "source_commit": os.environ.get("GITHUB_SHA", ""),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "profile_id": PROFILE_ID,
        "display_name": profile["display_name"],
        "factory_theme_count": EXPECTED_THEME_COUNT,
        "filter_ready_nature_assets": factory[PROFILE_ID]["nature_assets"],
        "exe_only_portability_verified": True,
        "files": {EXE_NAME: binary,
                  PORTABLE_ZIP: record(portable_zip),
                  THEME_ZIP: record(theme_zip)},
        "theme_files": {relative: record(ROOT / relative)
                        for relative in (profile_relative, catalog_relative)},
    }
    report_path = output / "AMERICAN_HARDWOODS_BUILD_REPORT.json"
    report_path.write_text(json.dumps(build_report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output / "SHA256SUMS.txt").write_text(checksums({
        EXE_NAME: exe,
        EXE_NAME + ".build.json": receipt_path,
        PORTABLE_ZIP: portable_zip,
        THEME_ZIP: theme_zip,
        report_path.name: report_path,
        saved_portability.name: saved_portability,
    }), encoding="ascii")
    for path in (portable_zip, theme_zip, report_path):
        print("Created: " + str(path))
    print("Packaged the checked Windows EXE and both matching theme JSON files.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("PACKAGE FAILED: " + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
