import os

from logging import getLogger

PKG_NAME = "markmeld"

_LOGGER = getLogger(PKG_NAME)

#  TODO: if it's a folder-style naming, shouldn't we put the output file
#  in that folder?
def glob_factory(vars):
    path = vars["path"]
    name_levels = 0
    if "name_levels" in vars:
        name_levels = vars["name_levels"]

    import glob

    globs = glob.glob(path)

    # Populate a targets array to return
    targets = {}
    for glob in globs:
        # Extract target name from path
        split_path = glob.split("/")
        file_name = os.path.splitext(split_path[-1])[0]
        tgt_array = [file_name]
        for lvl in range(1, int(name_levels)):
            tgt_array.insert(0, split_path[-(lvl+1)])

        tgt = "/".join(tgt_array)
        output_file = f"{tgt}.pdf"
        _LOGGER.debug(f"Found target: {tgt}")
        targets[tgt] = {
            "output_file": output_file,
            "data_md": {
                "data": glob,
            },
        }
        if "glob_variables" in vars:
            targets[tgt].update(vars["glob_variables"])
    return targets

