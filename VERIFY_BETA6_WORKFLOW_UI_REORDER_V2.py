from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parent
GUI = ROOT / "tgc_gui.py"


def fail(message):
    print("FAIL - " + message)
    raise SystemExit(1)


def main():
    if not GUI.is_file():
        fail("tgc_gui.py was not found")

    source = GUI.read_text(encoding="utf-8")

    required = [
        "BETA6_WORKFLOW_UI_REORDER_V2",
        "nb.add(lidar, text='Load OSM and Process LiDAR/DEM')",
        "localOSMSourceFrame = Frame(lidar, bg=check_bg)",
        "text=\"Local OSM File (blank = online)\"",
        "local_osm_entry = tk.Entry(\n    localOSMSourceFrame",
        "cfsWorkflowFrame = Frame(courseControlFrame, bg=bg_color)",
        "text=\"CFS Alignment Viewer...\"",
        "text=\"Rebuild Mask from Current OSM Alignment...\"",
        "Before importing, finalize the CFS alignment, rebuild the aligned mask",
        "osm_mask_status_label.configure(fg=\"black\")",
        "backgroundCheck.select()",
    ]
    missing = [needle for needle in required if needle not in source]
    if missing:
        print("FAIL - missing workflow marker(s):")
        for needle in missing:
            print("  " + needle)
        return 2

    centered_pack = "cfsWorkflowFrame.pack(padx=10, pady=(10, 4))"
    if centered_pack not in source:
        fail("CFS Viewer / Rebuild Mask workflow frame is not centered")
    cfs_pack_line = next(
        (line.strip() for line in source.splitlines() if line.strip().startswith("cfsWorkflowFrame.pack(")),
        "",
    )
    if "anchor=" in cfs_pack_line or "side=" in cfs_pack_line:
        fail("CFS workflow frame still has an explicit side/anchor instead of centered packing")

    if source.count("options_entries_dict = {}") != 1:
        fail("options_entries_dict must be initialized exactly once")

    shared_state = source.index("options_entries_dict = {}")
    lidar_tab = source.index("## Lidar Tab")
    osm_source_frame = source.index("localOSMSourceFrame = Frame(lidar")
    lidar_controls = source.index("lidarControlFrame = Frame(lidar")
    if not (shared_state < lidar_tab < osm_source_frame < lidar_controls):
        fail("Local OSM selector is not the topmost LiDAR/DEM workflow control")

    if 'Label(osmSubFrame, text="Local OSM File (blank = online)"' in source:
        fail("Local OSM selector still exists in Import Terrain and Features options")
    if "local_osm_entry.grid(" in source:
        fail("Local OSM entry is still grid-managed in the old OSM options frame")

    cfs_workflow = source.index("cfsWorkflowFrame = Frame(courseControlFrame")
    import_button = source.index(
        'coursebutton = Button(courseControlFrame, text="Select and Import Heightmap and OSM into Course"'
    )
    if cfs_workflow >= import_button:
        fail("CFS alignment workflow is not positioned before course import")

    status_block = source[source.index("osm_mask_status_label = Label("):import_button]
    if 'fg="black"' not in status_block or 'bg=check_bg' not in status_block:
        fail("OSM mask status blurb is not black text on the light workflow strip")

    reminder_start = source.index("courseImportReminder = Label(")
    reminder_end = source.index("def _scheduleOSMMaskStatusRefresh", reminder_start)
    reminder_block = source[reminder_start:reminder_end]
    if 'fg="black"' not in reminder_block or 'bg=check_bg' not in reminder_block:
        fail("manual mask-edit reminder is not black text on the light workflow strip")

    if "backgroundCheck.deselect()" in source:
        fail("Add Background Terrain/Remove Cliffs is still OFF by default")

    py_compile.compile(str(GUI), doraise=True)

    print("PASS: Local OSM selection is the topmost item on Load OSM and Process LiDAR/DEM.")
    print("PASS: CFS alignment and aligned-mask rebuild precede course import.")
    print("PASS: workflow blurbs use black text on a light background.")
    print("PASS: Add Background Terrain/Remove Cliffs is ON by default.")
    print("PASS: CFS Viewer and Rebuild Mask buttons are centered as one workflow group.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
