"""TGC Designer Tools 2K25 Beta 8.5 entry point."""
import sys

if '--verify-filter-ready' in sys.argv:
    from VERIFY_BETA8_5_FILTER_READY import verify
    verify()
elif '--verify-graduated-background' in sys.argv:
    from VERIFY_BETA8_4_GRADUATED_BACKGROUND import verify
    verify()
elif '--verify-theme-planting' in sys.argv:
    from VERIFY_BETA8_THEME_PLANTING import verify
    verify()
else:
    # Preserve every existing import/verification route and normal GUI startup.
    import tgc_tree_size_test1_entry
