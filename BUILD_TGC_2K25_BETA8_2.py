"""Build and validate the Beta 8.2 Windows executable using the retained pipeline."""
import sys
from BUILD_TGC_2K25_BETA8 import main as build

APP_TITLE='TGC Designer Tools 2K25 - Beta 8.2'
VERSION='v0.5.0-2k25-beta8.2'
EXE_NAME='tgc_gui_2k25_beta8_2'

if __name__ == '__main__':
    try:
        build(app_title=APP_TITLE, version=VERSION, exe_name=EXE_NAME, parking_release=True)
    except Exception as exc:
        print('BUILD FAILED: ' + str(exc), file=sys.stderr, flush=True)
        sys.exit(1)
