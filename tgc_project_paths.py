"""Beta 7: select CFS inputs from the active project, never another project's cache.

No geometry, datum, saved mask, or alignment offsets are changed here.
"""
from pathlib import Path

MARKER = 'TGC_BETA7_CURRENT_PROJECT_CFS_V1'


def current_project_folder(root):
    value = str(getattr(root, 'filename', '') or '').strip()
    return Path(value).expanduser().resolve() if value else Path.cwd().resolve()


def select_heightmap_folder(root, askdirectory, printf=print, title=None):
    """Use current project directly if ready; otherwise browse FROM that folder.

    A user may explicitly choose an external heightmap folder. That selection is
    never silently used as the default for a different/current project later.
    """
    project = current_project_folder(root)
    printf('CFS current project folder: ' + str(project))
    if (project / 'heightmap.npy').is_file():
        selected = project
    else:
        choice = askdirectory(
            initialdir=str(project), parent=root,
            title=title or 'Select heightmap folder for the current project',
        )
        if not choice:
            return ''
        selected = Path(choice).expanduser().resolve()
    if not (selected / 'heightmap.npy').is_file():
        printf('CFS NOTICE: no heightmap.npy in ' + str(selected) +
               '; no viewer opened or mask rebuilt. Choose the processed heightmap folder.')
        return ''
    printf('CFS heightmap folder: ' + str(selected))
    if selected != project:
        printf('CFS NOTICE: using the external heightmap folder explicitly selected for this operation.')
    return str(selected)
