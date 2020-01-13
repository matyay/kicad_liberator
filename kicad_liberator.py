#!/usr/bin/env python3
"""
KiCad liberator

A python script that allows to "liberate" a KiCad project making it
independed from any locally installed libraries. Such a project can
then be opened on any system.
"""
import argparse
import configparser
import os
from shutil import copy
import shlex

from collections import namedtuple, defaultdict

import bracket_tree

# =============================================================================

Symbol = namedtuple("Symbol", "name lib")
Footprint = namedtuple("Footprint", "name lib")
Library = namedtuple("Library", "name filename")

# =============================================================================


class CaseConfigParser(configparser.ConfigParser):
    """
    A Python's config parser that preserves option case.
    """
    def optionxform(self, optionstr):
        return optionstr

# =============================================================================


def load_kicad_env_vars(file_name):
    """
    Loads KiCad environmental variables from the "kicad_common" file.
    """

    # Load the "kicad_common" file
    with open(file_name, "r") as fp:
        config = fp.readlines()

    # The "kicad_common" file lacks a section name at the beginning, so add
    # it here to make the ConfigParser happy.
    config = ["[General]"] + config
    config = "\n".join(config)

    # Parse the config
    parser = CaseConfigParser()
    parser.read_string(config)

    # Look for "EnvironmentVariables"
    env_vars = {v[0]: v[1] for v in parser.items("EnvironmentVariables", raw=True)}
    return env_vars


def load_lib_table(file_name):
    """
    Load library names and file names from fp-lib-table or sym-lib-table
    file.
    """

    # Load the file
    with open(file_name, "r") as fp:
        root = bracket_tree.parse(fp.read())

    # The root node should be "sym_lib_table" or "fp_lib_table"
    assert root.keyword == "sym_lib_table" or root.keyword == "fp_lib_table"

    # Process all "lib" children
    libs = set()
    for node in root.findall("lib"):
        name = node.find("name").attributes[0]
        type = node.find("type").attributes[0]
        uri  = node.find("uri" ).attributes[0]

        if type not in ["Legacy", "KiCad"]:
            print("WARNING: Library type '{}' not supported!".format(type))
            continue

        libs.add(Library(name, uri))

    return libs

# =============================================================================


def find_project_files(path):
    """
    Finds KiCad project files in the given path.
    """

    project = {}

    files = os.listdir(path)

    # Find the .pro file
    pro = [f for f in files if f.lower().endswith(".pro")]
    if len(pro) == 0:
        raise RuntimeError("No KiCad project file found!")
    if len(pro) > 1:
        raise RuntimeError("Multiple KiCad project files found!")
    
    project["pro"] = pro[0]    
    
    # Schematic and board files
    project["sch"] = [f for f in files if f.lower().endswith(".sch")]
    project["brd"] = [f for f in files if f.lower().endswith(".kicad_pcb")]

    return project


def identify_used_symbols_and_footprints(sch_file):
    """
    Returns a set of used symbols and footprints in a schematic sheet.
    """

    symbols = set()
    footprints = set()    

    with open(sch_file, "r") as fp:
        section = None

        for l in fp:
            l = l.strip()

            # Identify section
            if section is None:
                if l == "$Comp":
                    section = l
                    continue

            elif section == "$Comp":
                if l == "$EndComp":
                    section = None
                    continue

            # "Comp" section
            if section == "$Comp":
                fields = shlex.split(l)

                # Got a symbol library reference field
                if len(fields) >= 2 and fields[0] == "L":
                    field = fields[1]

                    # Separate library and symbol name
                    if ":" in field:
                        lib, symbol = field.split(":")
                    else:
                        lib = None
                        symbol = field

                    # Add to the set
                    symbols.add(Symbol(
                        name = symbol,
                        lib = lib
                        ))

                # Got a footprint reference field
                if len(fields) >= 3 and fields[0] == "F" and fields[1] == "2":
                    field = fields[2]
                    if field != "":

                        # Separate library and symbol name
                        if ":" in field:
                            lib, footprint = field.split(":")
                        else:
                            lib = None
                            footprint = field

                        # Add to the set
                        footprints.add(Footprint(
                            name = footprint,
                            lib = lib
                        ))

    return symbols, footprints


def gather_footprints_and_identify_models(brd_file):
    """
    Gathers footprint definitions from the PCB file and identifies 3D models
    used by them.
    """

    # Load the PCB
    with open(brd_file, "r") as fp:
        root = bracket_tree.parse(fp.read())

    # The root should be "kicad_pcb"
    assert root.keyword == "kicad_pcb"

    # Look for modules and models
    footprints = {}
    models = set()

    for node in root.children:
        if node.keyword != "module":
            continue

        footprint = node.attributes[0]

        # Get footprint library and its name
        if ":" in footprint:
            lib, name = footprint.split(":")
        else:
            lib = None
            name = footprint

        # Store
        footprint = Footprint(name = name, lib = lib)
        footprints[footprint] = node

        # Look for "model"
        for item in node.children:
            if item.keyword != "model":
                continue

            model = item.attributes[0]
            models.add(model)

    return footprints, models


def identify_used_models(footprints, footprint_libs):
    """
    Scans footprint files and identifies 3D models used there
    """
    models = set()

    # Group libraries by name
    libs_by_name = {l.name: l.filename for l in footprint_libs}

    # Process footprints
    for footprint in footprints:

        # Library used in project but not found.
        if footprint.lib not in libs_by_name:
            continue

        lib_file = libs_by_name[footprint.lib]
        src_file = os.path.join(lib_file, footprint.name + ".kicad_mod")

        # Footprint not found in the library
        if not os.path.isfile(src_file):
            continue

        # Load the footprint
        with open(src_file, "r") as fp:
            root = bracket_tree.parse(fp.read())

        # The root should be "module"
        assert root.keyword == "module"

        # Look for "model"
        for node in root.children:
            if node.keyword != "model":
                continue

            model = node.attributes[0]
            models.add(model)

    return models

# =============================================================================


def substitute_env_vars(string, env_vars):
    """
    Substitute values of environmental variables in a string
    """

    # Replace an environmental variable
    if "${" in string and "}" in string:

        for var, value in env_vars.items():
            tag = "${" + var + "}"
            string = string.replace(tag, value)

    return string

# =============================================================================


def grab_symbol(lib_data, name):
    """
    Given a list of lines of a symbol library file, grabs the intersting symbol
    definition and returns it. Returns None if the symbol was not found.
    """

    # Add a comment preceeding symbol definition
    symbol_data = [
    "#",
    "# {}".format(name),
    "#",
    ]

    def_data = []
    in_def = False

    # Parse the library data
    for l in lib_data:
        l = l.strip()

        # Begin symbol definition
        if not in_def and l.startswith("DEF"):
            in_def = True
            def_data = []           

        # Copy lines
        if in_def:
            def_data.append(l)

        # End symbol definition
        if in_def and l == "ENDDEF":
            in_def = False

            # Check if this is the symbol that we are looking for
            for l in def_data:
                fields = l.strip().split()

                if len(fields) >= 2:

                    # DEF
                    if fields[0] == "DEF" and fields[1] == name:
                        symbol_data += def_data
                        return symbol_data

                    # ALIAS
                    if fields[0] == "ALIAS" and fields[1] == name:
                        symbol_data += def_data
                        return symbol_data

    # Symbol not found, return None
    return None
                

def collect_symbols(symbols, symbol_libs):
    """
    Collects symbols definitions from multiple symbol librarys.
    """

    # Group symbols by libraries
    symbols_by_lib = defaultdict(lambda: set())
    for symbol in symbols:
        symbols_by_lib[symbol.lib].add(symbol.name)

    # Group libraries by name
    libs_by_name = {l.name: l.filename for l in symbol_libs}

    # Grab symbol definitions from each library
    symbol_data = {}
    for lib, lib_symbols in symbols_by_lib.items():

        # Library used in project but not found.
        if lib not in libs_by_name or not os.path.isfile(libs_by_name[lib]):
            print(" ERROR: Library '{}' for symbols '{}' not found!".format(lib, ",".join(lib_symbols)))
            continue

        # Load the library content
        lib_file = libs_by_name[lib]
        with open(lib_file, "r") as fp:
            lib_data = fp.readlines()

        # Grab symbols
        for name in lib_symbols:

            # Grab
            data = grab_symbol(lib_data, name)
            if data is None:
                print(" ERROR: Symbol '{}' not found in '{}'".format(name, lib))
                continue
 
            # Add to definition
            key = Symbol(name, lib)
            symbol_data[key] = data

    return symbol_data


def process_symbol_defs(symbol_defs, symbol_map):
    """
    Modifies symbol definition according to the symbol map
    """

    # Process all definitions
    new_defs = {}

    for symbol, symbol_data in symbol_defs.items():
        new_name = symbol_map[symbol].name
        new_data = []

        # Process the definition
        for l in symbol_data:
            fields = l.strip().split()

            if len(fields) >= 2:

                # Header comment
                if fields[0] == "#" and fields[1] == symbol.name:
                    l = "# {}".format(new_name)

                # DEF
                elif fields[0] == "DEF" and fields[1] == symbol.name:
                    l = fields[0] + " " + new_name + " " + " ".join(fields[2:])

                # ALIAS
                elif fields[0] == "ALIAS" and fields[1] == symbol.name:
                    l = fields[0] + " " + new_name + " " + " ".join(fields[2:])

            new_data.append(l)

        # Store new data
        new_defs[symbol] = new_data

    return new_defs

# =============================================================================


def preprocess_pcb_footprints(footprints):
    """
    Processes footprints extracted from PCB to make them generic and to be
    placed in the new library
    """

    # A helper function for processing element rotations
    def cancel_rotation(node, rotation):

        # Skip those. The "model" element seems to have rotation relative to
        # the footprint.
        if node.keyword in ["at", "model"]:
            return

        # We have the "at" child
        at = node.find("at")
        if at is not None:

            # Get its rotation
            coords = at.attributes
            rot = 0.0 if len(coords) < 3 else float(coords[2])

            # Cancel it
            rot -= rotation
            rot  = "{:.3f}".format(rot)

            # Replace the "at" node
            new_at = bracket_tree.Node(node, "at", [coords[0], coords[1], rot])
            node.replace(at, new_at)

        # Recurse
        for child in node.children:
            cancel_rotation(child, rotation)

    # Process footprints
    for footprint, root in footprints.items():

        # Remove the "at" node, get the footprint rotation.
        node = root.find("at")
        if node is not None:
            coords = node.attributes
            rotation = 0.0 if len(coords) < 3 else float(coords[2])
            root.remove(node)
        else:
            rotation = 0.0

        # Cancel rotation of all elements of the footprint
        for node in root.children:
            cancel_rotation(node, rotation)

        # Texts
        for node in root.findall("fp_text"):

            if node.attributes[0] == "reference":
                node.replace(node.attributes[1], "REF**")

            if node.attributes[0] == "value":
                node.replace(node.attributes[1], footprint.name)

    return footprints


def collect_footprints_from_libraries(footprints, footprint_libs):
    """
    Collects footprint definition files from multiple libraries.
    """

    # Group libraries by name
    libs_by_name = {l.name: l.filename for l in footprint_libs}

    # Get footprint definition from each library
    footprint_defs = {}
    for footprint in footprints:

        # Library used in project but not found.
        if footprint.lib not in libs_by_name:
            print(" ERROR: Library '{}' for footprint '{}' not found!".format(footprint.lib, footprint.name))
            footprint_defs[footprint] = None
            continue

        lib_file = libs_by_name[footprint.lib]
        src_file = os.path.join(lib_file, footprint.name + ".kicad_mod")

        # Footprint not found in the library
        if not os.path.isfile(src_file):
            print(" ERROR: Footrpint '{}' not found in '{}'".format(footprint.name, footprint.lib))
            footprint_defs[footprint] = None
            continue

        # Load the footprint
        with open(src_file, "r") as fp:
            root = bracket_tree.parse(fp.read())

        # The root should be "module"
        assert root.keyword == "module"

        # Add
        footprint_defs[footprint] = root

    return footprint_defs


def process_footprints(footprint_defs, footprint_map, model_map, path):
    """
    Processes footprint definitions. Renames footprints according to the
    footprint map and renames 3D model file names accordinf to the model
    map. Writes files to the destination path.
    """

    # Create the output directory
    os.makedirs(path, exist_ok=True)

    written_files = set()

    # Process footprint data
    for footprint, root in footprint_defs.items():

        if root is None:
            continue

        new_name = footprint_map[footprint].name
        dst_file = os.path.join(path, new_name + ".kicad_mod")

        # Change the module name
        root.child[0] = new_name

        # Change the 3D model name
        for node in root.children:
            if node.keyword != "model":
                continue

            model = node.attributes[0]
            new_name = model_map[model]
            node.child[0] = new_name

        # Check for duplicates
        if dst_file in written_files:
            print(" ERROR: Duplcate footprint '{}'".format(new_name))
            continue

        # Write the footrpint
        bracket_tree.save(dst_file, root)
        written_files.add(dst_file)

# =============================================================================


def collect_models(models, path):
    """
    Collect 3D models from libraries and put them in a common folder.
    """

    # Create the output directory
    os.makedirs(path, exist_ok=True)

    written_files = set()

    # Copy model files
    for model in models:

        src_file = model
        dst_file = os.path.join(path, os.path.basename(model))

        # Model file not found
        if not os.path.isfile(src_file):
            print(" ERROR: Model '{}' not found".format(model))
            continue

        # Check for duplicates
        if dst_file in written_files:
            print(" ERROR: Duplcate model '{}'".format(os.path.basename(model)))
            continue

        # Copy the file
        copy(src_file, dst_file)
        written_files.add(dst_file)


# =============================================================================


def process_schematics(inp_sch_file, out_sch_file, symbol_map=None, footprint_map=None):
    """
    Remaps library references to symbol names in a schematic file.
    """

    # Load schematic file
    with open(inp_sch_file, "r") as fp:
        sch_data = fp.readlines()

    # Remap symbol references
    if symbol_map:
        for i, line in enumerate(sch_data):
            fields = line.strip().split()

            # Got a symbol library reference, replace it
            if len(fields) >= 2 and fields[0] == "L":
                for s1, s2 in symbol_map.items():
                    tag1 = "{}:{}".format(s1.lib, s1.name)

                    # Got a match, replace
                    if fields[1] == tag1:
                        tag2 = "{}:{}".format(s2.lib, s2.name)
                        sch_data[i] = sch_data[i].replace(tag1, tag2)
                        break

    # Remap footprint references
    if footprint_map:
        for i, line in enumerate(sch_data):
            fields = line.strip().split()

            # Got a footprint library reference, replace it
            if len(fields) >= 3 and fields[0] == "F" and fields[1] == "2":
                for f1, f2 in footprint_map.items():
                    tag1 = "\"{}:{}\"".format(f1.lib, f1.name)

                    # Got a match, replace
                    if fields[2] == tag1:
                        tag2 = "\"{}:{}\"".format(f2.lib, f2.name)
                        sch_data[i] = sch_data[i].replace(tag1, tag2)
                        break

    # Write the modified schematic file
    with open(out_sch_file, "w") as fp:
        fp.writelines(sch_data)


def process_boards(inp_brd_file, out_brd_file, footprint_map, model_map):
    """
    Remaps library references to footprint names in a board file.
    """

    # Load board file
    with open(inp_brd_file, "r") as fp:
        brd_data = fp.read()

    # FIXME: Possible symbol vs. footprint name conflict!
    # This is done in a "brutal" way. Should read the PCB structure, replace
    # attributes of nodes and write it back.
    for f1, f2 in footprint_map.items():
        tag1 = "{}:{}".format(f1.lib, f1.name)
        tag2 = "{}:{}".format(f2.lib, f2.name)

        brd_data = brd_data.replace(tag1, tag2)

    for m1, m2 in model_map.items():
        brd_data = brd_data.replace(m1, m2)

    # Write the modified board file
    with open(out_brd_file, "w") as fp:
        fp.write(brd_data)

# =============================================================================

def main():

    # Parse arguments
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter
        )

    parser.add_argument(
        "-i",
        required=True,
        type=str,
        help="KiCad project path"
    )

    parser.add_argument(
        "-o",
        required=True,
        type=str,
        help="Output path for the \"liberated\" project"
    )

    args = parser.parse_args()
    inp_path = args.i

    # .....................................................

    # Load global KiCad configuration
    print("Loading KiCad configuration...")

    # FIXME: How that would work on Windows/MaxOs ??
    # Where there is KiCad configuration stored ?
    home_dir  = os.path.expanduser("~")
    kicad_dir = os.path.join(home_dir, os.path.join(".config", "kicad"))

    # Environmental variables
    file_name = os.path.join(kicad_dir, "kicad_common")
    if os.path.isfile(file_name):
        kicad_env_vars = load_kicad_env_vars(file_name)
    else:
        kicad_env_vars = {}

    # Add KIPRJMOD environmental variable which points to the project path
    kicad_env_vars["KIPRJMOD"] = inp_path

    # Load globally available symbol libraries
    symbol_libs = set()

    file_name = os.path.join(kicad_dir, "sym-lib-table")
    if os.path.isfile(file_name):
        symbol_libs |= load_lib_table(file_name)

    # Load globally available footprint libraries
    footprint_libs = set()

    file_name = os.path.join(kicad_dir, "fp-lib-table")
    if os.path.isfile(file_name):
        footprint_libs |= load_lib_table(file_name)

    # .....................................................

    # Identify project files
    proj = find_project_files(inp_path)

    # Get project name
    proj_name = proj["pro"].rsplit(".", maxsplit=1)[0]

    # Dump some info
    print("")
    print("Project '{}'".format(proj_name))
    print("", proj["pro"])

    print("Schematics:")
    for f in proj["sch"]:
        print("", f)

    print("Boards:")
    for f in proj["brd"]:
        print("", f)

    print("")

    # Load project library tables
    print("Loading library tables...")

    file_name = os.path.join(inp_path, "sym-lib-table")
    if os.path.isfile(file_name):
        symbol_libs |= load_lib_table(file_name)

    file_name = os.path.join(inp_path, "fp-lib-table")
    if os.path.isfile(file_name):
        footprint_libs |= load_lib_table(file_name)

    # Substitute environmental variables in library file names
    symbol_libs = [Library(l.name, substitute_env_vars(l.filename, kicad_env_vars))
        for l in symbol_libs]

    footprint_libs = [Library(l.name, substitute_env_vars(l.filename, kicad_env_vars))
        for l in footprint_libs]

    # .....................................................

    # Identify used symbols and footprints
    print("Identifying used schematic symbols and footrpints...")

    lib_symbols = set()
    lib_footprints = set()
    lib_models = set()
    pcb_footprints = {}
    pcb_models = set()

    for f in proj["sch"]:
        sch_file = os.path.join(inp_path, f)

        syms, fps = identify_used_symbols_and_footprints(sch_file)
        lib_symbols    |= syms
        lib_footprints |= fps

    # Identify used footprints and 3d models
    print("Identifying used PCB footprints and 3D models...")

    for f in proj["brd"]:
        brd_file = os.path.join(inp_path, f)
        fps, mdls = gather_footprints_and_identify_models(brd_file)
        pcb_footprints.update(fps)
        pcb_models |= mdls

    # Identify 3D models used by footprint libraries
    lib_models |= identify_used_models(lib_footprints, footprint_libs)

    # Preprocess PCB footprints
    pcb_footprints = preprocess_pcb_footprints(pcb_footprints)
   
    # .....................................................

    # Build symbol map
    symbol_lib = Library(
        name=proj_name, 
        filename=proj_name + ".lib"
        )

    symbol_map = {}
    used_names = set()

    # FIXME: This will fail if there are two symbols with the same name in
    # different libraries but one of them has an ALIAS.
    for symbol in lib_symbols:
        new_name  = symbol.name
        suffix_id = 0

        while new_name in used_names:
            suffix_id += 1
            new_name = symbol.name + "_{:02d}".format(suffix_id)
        
        symbol_map[symbol] = Symbol(
            name=new_name,
            lib=symbol_lib.name
            )

        used_names.add(new_name)

    # Build footprint map
    all_footprints = set(lib_footprints | set(pcb_footprints.keys()))

    footprint_lib = Library(
        name=proj_name,
        filename="footprints.pretty"
        )

    footprint_map = {}
    used_names = set()

    for footprint in all_footprints:
        new_name  = footprint.name
        suffix_id = 0

        while new_name in used_names:
            suffix_id += 1
            new_name = footprint.name + "_{:02d}".format(suffix_id)
        
        footprint_map[footprint] = Footprint(
            name=new_name,
            lib=footprint_lib.name
            )

        used_names.add(new_name)

    # Build 3d model map
    all_models = lib_models | pcb_models
    model_lib  = os.path.join("${KIPRJMOD}", "models")

    model_map = {}
    used_names = set()

    for model in all_models:
        name = os.path.basename(model)
        new_name = name
        suffix = 0

        while new_name in used_names:
            suffix_id += 1
            parts = os.path.splitext(name)
            new_name = parts[0] + "_{:02d}".format(suffix_id) + parts[1]

        model_map[model] = os.path.join(model_lib, new_name)
        used_names.add(new_name)

    # .....................................................

    out_path = args.o

    # Initialize "liberated" project
    os.makedirs(out_path, exist_ok=True)
    copy(os.path.join(inp_path, proj["pro"]),
         os.path.join(out_path, proj["pro"]))

    # .....................................................

    # Collect symbols
    print("Collecting schematic symbols from libraries...")
    lib_symbols = collect_symbols(lib_symbols, symbol_libs)

    # Remap names in symbol defs
    lib_symbols = process_symbol_defs(lib_symbols, symbol_map)

    # Write the new symbol library
    lib_data = [
        "EESchema-LIBRARY Version 2.4",
        "#encoding utf-8",
    ]

    for symbol_def in lib_symbols.values():
        lib_data.extend(symbol_def)

    lib_data.extend([
    "#",
    "#End Library",
    ])

    lib_file = os.path.join(out_path, symbol_lib.filename)
    with open(lib_file, "w") as fp:
        fp.write("\n".join(lib_data))


    # Write sym-lib-table
    root = bracket_tree.Node(None, "sym_lib_table")
    node = bracket_tree.Node(root, "lib")
    root.add(node)
    node.add(bracket_tree.Node(node, "name",    [symbol_lib.name]))
    node.add(bracket_tree.Node(node, "type",    ["Legacy"]))
    node.add(bracket_tree.Node(node, "uri",     ["${KIPRJMOD}/" + symbol_lib.filename]))
    node.add(bracket_tree.Node(node, "options", [""]))
    node.add(bracket_tree.Node(node, "descr",   [""]))

    file_name = os.path.join(out_path, "sym-lib-table")
    bracket_tree.save(file_name, root)

    # .....................................................

    # Collect footprints from footprint libraries
    print("Collecting PCB footprints from libraries...")
    lib_footprints = collect_footprints_from_libraries(lib_footprints, footprint_libs)

    # For missing footprints, take their definitions directly from the PCB
    for footprint in lib_footprints:

        if lib_footprints[footprint] is not None:
            continue

        if footprint not in pcb_footprints:
            print(" ERROR: Footprint '{}' not found in PCB(s)!".format(footprint.name))
            continue

        print(" Extracting '{}' from PCB".format(footprint.name))
        lib_footprints[footprint] = pcb_footprints[footprint]

    # Write footprints to the new library
    process_footprints(lib_footprints, footprint_map, model_map,
                       os.path.join(out_path, footprint_lib.filename))

    # Write fp-lib-table
    root = bracket_tree.Node(None, "fp_lib_table")
    node = bracket_tree.Node(root, "lib")
    root.add(node)
    node.add(bracket_tree.Node(node, "name",    [footprint_lib.name]))
    node.add(bracket_tree.Node(node, "type",    ["KiCad"]))
    node.add(bracket_tree.Node(node, "uri",     [os.path.join("${KIPRJMOD}", footprint_lib.filename)]))
    node.add(bracket_tree.Node(node, "options", [""]))
    node.add(bracket_tree.Node(node, "descr",   [""]))

    file_name = os.path.join(out_path, "fp-lib-table")
    bracket_tree.save(file_name, root)

    # .....................................................

    # Substitute environmental variables in model names
    all_models = [substitute_env_vars(m, kicad_env_vars) for m in all_models]
    model_lib = substitute_env_vars(model_lib, {"KIPRJMOD": out_path})

    # Collect 3d models
    print("Collecting 3D models from libraries...")
    collect_models(all_models, model_lib)

    # .....................................................

    # Process schematic files, substitute symbol and footprint references.
    print("Processing schematic files...")
    for sch_file in proj["sch"]:
        print(" {}".format(sch_file))
        process_schematics(
            os.path.join(inp_path, sch_file),
            os.path.join(out_path, sch_file),
            symbol_map, footprint_map
        )

    # Process board files, substitute footprint references.
    print("Processing board files...")
    for brd_file in proj["brd"]:
        print(" {}".format(brd_file))
        process_boards(
            os.path.join(inp_path, brd_file),
            os.path.join(out_path, brd_file),
            footprint_map,
            model_map
        )

    print("Done.")        

# =============================================================================


if __name__ == "__main__":
    main()
