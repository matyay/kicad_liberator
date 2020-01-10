# KiCad Liberator

An utility script that allows to "liberate" a KiCad project from all symbol/footprint/model libraries installed in one's system.

## Usage

Run the script providing it with the source project folder and destination path to write the modified project to.

```
python3 kicad_liberator.py -i <path_to_the_project> -o <destination_path>
```

## How it works

In a nutshell, the script does the following:

- Identifies project files and its name (there has to be only one `.pro` file in the source folder!)
- Loads system-wide KiCad configuration and library tables, determines its environmental variables.
- Identifies all symbols, footprints and models used in the project by scanning all `.sch` and `.kicad_pcb` files.
- Collects all symbols, footprints and models from all used libraries and puts them into new libraries local to the project.
- Convert references to all symbol/footprints/models in schematic and board files to point to the new libraries.
- Writes everything into the destination path.

The script does NOT modify the original project, it creates a new one with the same name.

## Remarks

Tested on Linux only. Should work on Windows/Mac but probably there's a need to modify the KiCad configuration loading. it's location is differen on each OS type (I guess).