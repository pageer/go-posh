#!/usr/bin/env python
# Copyright (c) 2002-2008 ActiveState Software.
# License: MIT License.
# Author: Trent Mick (trentm at google's mail thing)

"""
    Quick directory changing.

    Usage:
        go [<shortcut>][/sub/dir/path]  # change directories
                                        # same as "go -c ..."
                                        # uses home directory by default
        go -c|-p|-o|-a|-d|-s ...        # cd, open, add, delete, set
        go --list [<pattern>]           # list matching shortcuts

    Options:
        -h, --help                      print this help and exit
        -V, --version                   print verion info and exit

        -c, --cd <path>                 cd to shortcut path in shell
        -p, --print <path>              print the shortcut path to STDOUT
        -s, --set <shortcut> <dir>      set a shortcut to <dir>
        -a, --add-current <shortcut>    add shortcut to current directory
        -d, --delete <shortcut>         delete the named shortcut
        -o, --open [<path>]             open the given shortcut path in
                                        a file manager, defaults
                                        to current directory.
        -l, --list [<pattern>]          list current shortcuts

    Generally you have a set of directories that you commonly visit.
    Typing these paths in full can be a pain. This script allows one to
    define a set of directory shortcuts to be able to quickly change to
    them. For example, I could define 'ko' to represent
    "D:\\trentm\\main\\Apps\\Komodo-devel", then
        C:\\> go ko
        D:\\trentm\\main\\Apps\\Komodo-devel>
    and
        C:\\> go ko/test
        D:\\trentm\\main\\Apps\\Komodo-devel\\test>

    As well, you can always use some standard shortcuts, such as '~'
    (home) and '...' (up two dirs).

    In addition, go supports resolving unique prefixes of both shortcuts
    and path components.  So the above example could also be written as:
        C:\\> go k/t
        D:\\trentm\\main\\Apps\\Komodo-devel\\test>
    This is assuming that no other shortcut starts with "k" and the
    Komodo-devel directory contains no other directory (files are OK)
    that starts with "t".

    See <http://code.google.com/p/go-tool/> for more information.
"""
# Dev Notes:
# - Shortcuts are stored in an XML file in your AppData folder.
#   On Windows this is typically:
#     <AppDataDir>\TrentMick\go\shortcuts.xml
#   On Linux (or other UN*X systems) this is typically:
#     ~/.go/shortcuts.xml

__version_info__ = (2, 1, 0)
__version__ = '.'.join(map(str, __version_info__))

import codecs
import fnmatch
import getopt
import os
import re
import sys
import tempfile
import warnings
import xml.dom.minidom

from os.path import expanduser, exists, join, normcase, normpath

#---- exceptions

class GoError(Exception):
    """External Go error"""

class InternalGoError(GoError):
    """Internal Go error"""
    def __str__(self):
        return GoError.__str__(self) + """

* * * * * * * * * * * * * * * * * * * * * * * * * * * *
* Please log a bug at                                 *
*    http://code.google.com/p/go-tool/issues/list     *
* to report this error. Thanks!                       *
* -- Trent                                            *
* * * * * * * * * * * * * * * * * * * * * * * * * * * *"""



#---- globals

_ENVAR = "GO_SHELL_SCRIPT"
_FILEMAN_ENV = "FILEMANAGER"


_gDriverFromShell = {
    "cmd": """\
@echo off
rem Windows shell driver for 'go' (http://code.google.com/p/go-tool/).
set GO_SHELL_SCRIPT=%TEMP%\\__tmp_go.bat
call python -m go %1 %2 %3 %4 %5 %6 %7 %8 %9
if exist %GO_SHELL_SCRIPT% call %GO_SHELL_SCRIPT%
set GO_SHELL_SCRIPT=""",
    "powershell": """\
# Windows Powershell driver for 'go' (http://code.google.com/p/go-tool/).
$env:SHELL = "powershell"
$env:GO_SHELL_SCRIPT=$env:TEMP+"\\__tmp_go.ps1"
python -m go $args
if (Test-Path $env:GO_SHELL_SCRIPT) {
    . $env:GO_SHELL_SCRIPT
}
$env:GO_SHELL_SCRIPT = '';
""",
    "sh": """\
# Bash shell driver for 'go' (http://code.google.com/p/go-tool/).
function go {
    export GO_SHELL_SCRIPT=$HOME/.__tmp_go.sh
    python -m go $*
    if [ -f $GO_SHELL_SCRIPT ] ; then
        source $GO_SHELL_SCRIPT
    fi
    unset GO_SHELL_SCRIPT
}""",
}



#---- public module interface

def get_shortcuts_file():
    """Return the path to the shortcuts file."""
    fname = "shortcuts.xml"
    if sys.platform.startswith("win"):
        # Favour ~/.go if shortcuts.xml already exists there, otherwise
        # favour CSIDL_APPDATA/... if have win32com to *find* that dir.
        dname = os.path.expanduser("~/.go")
        shortcuts_file = os.path.join(dname, fname)
        if not os.path.isfile(shortcuts_file):
            try:
                from win32com.shell import shellcon, shell
                dname = os.path.join(
                    shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, 0, 0),
                    "TrentMick", "Go")
                shortcuts_file = os.path.join(dname, fname)
            except ImportError:
                pass
    else:
        dname = os.path.expanduser("~/.go")
        shortcuts_file = os.path.join(dname, fname)
    return shortcuts_file


def get_default_shortcuts():
    """Return the dictionary of default shortcuts."""
    if sys.platform == "win32" and sys.version.startswith("2.3."):
        warnings.filterwarnings("ignore", module="fcntl", lineno=7)
    shortcuts = {
        '.': os.curdir,
        '..': os.pardir,
        '...': os.path.join(os.pardir, os.pardir),
        'tmp': tempfile.gettempdir(),
    }
    try:
        shortcuts['~'] = os.environ['HOME']
    except KeyError:
        try:
            shortcuts['~'] = os.environ['USERPROFILE']
        except KeyError:
            pass
    try:
        shortcuts['-'] = os.environ['OLDPWD']
    except KeyError:
        pass
    return shortcuts


def set_shortcut(name, value):
    """Add the given shortcut mapping to the XML database.

        <shortcuts version="...">
            <shortcut name="..." value="..."/>
        </shortcuts>

    A value of None deletes the named shortcut.
    """
    shortcuts_xml = get_shortcuts_file()
    if os.path.isfile(shortcuts_xml):
        dom = xml.dom.minidom.parse(shortcuts_xml)
    else:
        dom = xml.dom.minidom.parseString(
                    '<shortcuts version="1.0"></shortcuts>')

    shortcuts = dom.getElementsByTagName("shortcuts")[0]
    for shortcut in shortcuts.getElementsByTagName("shortcut"):
        if shortcut.getAttribute("name") == name:
            if value:
                shortcut.setAttribute("value", value)
            else:
                shortcuts.removeChild(shortcut)
            break
    else:
        if value:
            shortcut = dom.createElement("shortcut")
            shortcut.setAttribute("name", name)
            shortcut.setAttribute("value", value)
            shortcuts.appendChild(shortcut)
        else:
            raise GoError("shortcut '%s' does not exist" % name)

    if not os.path.isdir(os.path.dirname(shortcuts_xml)):
        os.makedirs(os.path.dirname(shortcuts_xml))
    with open(shortcuts_xml, 'w', encoding='utf-8') as fout:
        fout.write(dom.toxml())


def get_shortcut():
    """Return the shortcut dictionary."""
    shortcuts = get_default_shortcuts()

    shortcuts_xml = get_shortcuts_file()
    if os.path.isfile(shortcuts_xml):
        dom = xml.dom.minidom.parse(shortcuts_xml)
        shortcuts_node = dom.getElementsByTagName("shortcuts")[0]
        for shortcut_node in shortcuts_node.getElementsByTagName("shortcut"):
            name = shortcut_node.getAttribute("name")
            value = shortcut_node.getAttribute("value")
            shortcuts[name] = value

    return shortcuts


def resolve_path(path):
    """Return a dir for the given <shortcut>[/<subpath>].

    Raises a GoError if the shortcut does not exist.
    """
    shortcuts = get_shortcut()

    if path:
        tagend = path.find('/')
        if tagend == -1:
            tagend = path.find('\\')
        if tagend == -1:
            tag, suffix = path, None
        else:
            tag, suffix = path[:tagend], path[tagend+1:]

        try:
            target = shortcuts[tag]
        except KeyError:
            # Bash will expand ~ (used as a shortcut) into the user's
            # actual home directory. We still want to support '~' as a
            # shortcut in Bash so try to determine if it is likely that
            # the user typed it and act accordingly.
            home = os.path.expanduser('~')
            if path.startswith(home) and path != home:
                tag, suffix = '~', path[len(home)+1:]
                target = shortcuts[tag]
            elif get_shortcut_prefix(tag, shortcuts) != 0:
                target = shortcuts[get_shortcut_prefix(tag, shortcuts)]
            elif os.path.isdir(path):
                target = ""
                suffix = path
            else:
                suffix = path
                target = tag
                if target == '':
                    target = os.path.sep
                elif not os.path.isdir(target):
                    target = '.'
                #raise
        if suffix:
            target = resolve_full_path(target, suffix)
    else:
        raise GoError("no path was given")

    return target

def resolve_full_path(prefix, suffix):
    """Try to get a full path from a suffix"""
    # If the path exists, then return it
    tmp = os.path.join(prefix, suffix)
    if os.path.isdir(tmp):
        return tmp

    comps = []
    head = suffix
    last_head = ''
    while head != last_head:
        last_head = head
        (head, tail) = os.path.split(head)
        comps.append(tail)

    comps.reverse()
    path = os.path.normpath(prefix)

    for comp in comps:
        tmp = os.path.join(path, comp)
        if os.path.isdir(tmp):
            path = tmp
        else:
            found = ''
            for directory in os.listdir(path):
                full_path = os.path.join(path, directory)
                if fnmatch.fnmatch(directory, comp+'*') and os.path.isdir(full_path):
                    if found == '':
                        found = directory
                    else:
                        raise GoError(f"Abmiguous path under {path}: '{found}', '{directory}'")
            if found == '':
                msg = "Unable to resolve '%s' under directory '%s'" % (comp, path)
                if prefix == '.':
                    msg = "Shortcut or directory not found: '%s'" % comp
                raise GoError(msg)
            path = os.path.join(path, found)
    return path


def get_shortcut_prefix(path, shortcuts):
    """Returns the full name for a shortcut based on a prefix.

    If the path is a unique prefix of one of the shortcuts, returns
    that shortcut's path.  If shortcut is not found, returns 0.
    Otherwise, throws an exception.
    """
    if path == '':
        return 0

    ret = []
    for name in shortcuts:
        if name == path:
            return name
        if name.startswith(path):
            ret.append(name)
    if len(ret) == 1:
        return ret[0]
    if len(ret) == 0:
        return 0
    raise GoError("ambiguous shortcut '" + path + "' - " + ', '.join(ret))


def generate_shell_script(script_name, path=None):
    """Generate a shell script with the given name to change to the
    given shortcut path.

    "scriptName" is the path to the script the create.
    "path" is the shortcut path, i.e. <shortcut>[/<subpath>]. If path is
        None (the default) a no-op script is written.
    """
    if path is None:
        target = None
    else:
        target = resolve_path(path)

    if sys.platform.startswith("win") and _get_shell() == 'powershell':
        with open(script_name, 'w', encoding='utf-8') as fbat:
            if target:
                drive, _ = os.path.splitdrive(target)
                if drive:
                    fbat.write('%s\n' % drive)
                fbat.write("$env:OLDPWD='%s'\n" % os.getcwd())
                fbat.write('cd "%s"\n' % target)
                fbat.write('$Host.UI.RawUI.WindowTitle = "%s"\n' % target)
    elif sys.platform.startswith("win"):
        with open(script_name, 'w', encoding='utf-8') as fbat:
            fbat.write('@echo off\n')
            if target:
                drive, _ = os.path.splitdrive(target)
                fbat.write('@echo off\n')
                if drive:
                    fbat.write('call %s\n' % drive)
                fbat.write('set OLDPWD=%s\n' % os.getcwd())
                fbat.write('call cd "%s"\n' % target)
                fbat.write('title "%s"\n' % target)
    else:
        with open(script_name, 'w', encoding='utf-8') as fsh:
            fsh.write('#!/bin/sh\n')
            if target:
                fsh.write('cd "%s"\n' % target)


def print_shortcuts(shortcuts, subheader=None):
    """Print out a table of defined shortcuts"""
    # Organize the shortcuts into groups.
    defaults = []
    for shortcut in get_default_shortcuts():
        defaults.append(shortcut)
    group_map = { # mapping of group regex to group order and title
        "^(%s)$" % '|'.join(defaults): (0, "Default shortcuts"),
        None: (1, "Custom shortcuts"),
    }
    grouped = {
        # <group title>: [<member shortcuts>...]
    }
    for shortcut in shortcuts:
        for pattern, (_, title) in group_map.items():
            if pattern and re.search(pattern, shortcut):
                if title in grouped:
                    grouped[title].append(shortcut)
                else:
                    grouped[title] = [shortcut]
                break
        else:
            title = "Custom shortcuts"
            if title in grouped:
                grouped[title].append(shortcut)
            else:
                grouped[title] = [shortcut]
    for member_list in grouped.values():
        member_list.sort()
    titles = list(group_map.values())
    titles.sort()

    # Construct the table.
    table = ""
    header = "Go Shortcuts"
    if subheader:
        header += ": " + subheader
    table += ' '*20 + header + '\n'
    table += ' '*20 + '='*len(header) + '\n'
    for _, title in titles:
        if title not in grouped:
            continue
        table += '\n' + title + ":\n"
        for shortcut in grouped[title]:
            directory = shortcuts[shortcut]
            table += "  %-20s  %s\n" % (shortcut, directory)

    # Display the table.
    sys.stdout.write(table)


def error(msg):
    """Display an error message and raise an exception"""
    sys.stderr.write("go: error: %s\n" % msg)


def _get_shell():
    if "SHELL" in os.environ:
        shell_path = os.environ["SHELL"]
        if "/bash" in shell_path or "/sh" in shell_path:
            return "sh"
        if "/tcsh" in shell_path or "/csh" in shell_path:
            return "csh"
        if "powershell" in shell_path:
            return "powershell"
    elif sys.platform == "win32":
        #assert "cmd.exe" in os.environ["ComSpec"]
        return "cmd"
    raise InternalGoError("couldn't determine your shell (SHELL=%r)"
                          % os.environ.get("SHELL"))

def setup():
    """Perform the wrapper script/alias setup."""
    shell = _get_shell()
    try:
        driver = _gDriverFromShell[shell]
    except KeyError as err:
        raise InternalGoError("don't know how to setup for your shell: {shell}") from err

    # Knowing the user's HOME dir will help later.
    nhome = None
    if "HOME" in os.environ:
        nhome = _normpath(os.environ["HOME"])
    elif "HOMEDRIVE" in os.environ and "HOMEPATH" in os.environ:
        nhome = _normpath(
            os.environ["HOMEDRIVE"] + os.environ["HOMEPATH"])

    print("* * *")


    if shell in ("cmd", "powershell"):
        # Need a install candidate dir for "go.bat"/"go.ps1".
        if shell == "cmd":
            shell_script_name = "go.bat"
        else:
            shell_script_name = "go.ps1"

        nprefix = _normpath(sys.prefix)
        ncandidates = set()
        candidates = []
        for directory in os.environ["PATH"].split(os.path.pathsep):
            ndir = _normpath(directory)
            if ndir.startswith(nprefix):
                if ndir not in ncandidates:
                    ncandidates.add(ndir)
                    candidates.append(directory)
            elif nhome and ndir.startswith(nhome) \
                 and ndir[len(nhome)+1:].count(os.path.sep) < 2:
                if ndir not in ncandidates:
                    ncandidates.add(ndir)
                    candidates.append(directory)
        #print candidates

        print("""\
It appears that `go' is not setup properly in your environment. Typing
`go' must end up calling `%s' somewhere on your PATH and *not* `go.py'
directly. This is how `go' can change the directory in your current shell.

You'll need a file "%s" with the following contents in a directory on
your PATH:

%s""" % (shell_script_name, shell_script_name, _indent(driver)))

        if candidates:
            print("\nCandidate directories are:\n")
            for i, directory in enumerate(candidates):
                print("  [%s] %s" % (i+1, directory))

            print()
            answer = _query_custom_answers(
                f"If you would like this script to create `{shell_script_name}' for you in\n"
                    "one of these directories, enter the number of that\n"
                    "directory. Otherwise, enter 'no' to not create `{shell_script_name}'." ,
                [str(i+1) for i in range(len(candidates))] + ["&no"],
                default="no",
            )
            if answer == "no":
                pass
            else:
                directory = candidates[int(answer)-1]
                path = join(directory, shell_script_name)
                print("\nCreating `%s'." % path)
                print("You should now be able to run `go --help'.")
                with open(path, 'w', encoding='utf-8') as file:
                    file.write(driver)
    elif shell == "sh":
        print("""\
It appears that `go' is not setup properly in your environment. Typing
`go' must end up calling the Bash function `go' and *not* `go.py'
directly. This is how `go' can change the directory in your current shell.

You'll need to have the following function in your shell startup script
(e.g. `.bashrc' or `.profile'):

%s

To just play around in your current shell, simple cut and paste this
function.""" % _indent(driver))

        candidates = ["~/.bashrc", "~/.bash_profile", "~/.bash_login",
                      "~/.profile"]
        candidates = [c for c in candidates if exists(expanduser(c))]
        if candidates:
            question = """\
Would you like this script to append `function go' to one of the following
Bash initialization scripts? If so, enter the number of the listed file.
Otherwise, enter `no'."""
            for i, path in enumerate(candidates):
                question += "\n (%d) %s" % (i+1, path)
            answers = [str(i+1) for i in range(len(candidates))] + ["&no"]
            print()
            answer = _query_custom_answers(question, answers, default="no")
            if answer == "no":
                pass
            else:
                path = candidates[int(answer)-1]
                xpath = expanduser(path)
                with codecs.open(xpath, 'a', encoding='utf-8') as file:
                    file.write('\n\n'+driver)
                print()
                print("`function go' appended to `%s'." % path)
                print("Run `source %s` to enable this for this shell." % path)
                print("You should then be able to run `go --help'.")
    else:
        print("""\
It appears that `go' is not setup properly in your environment. Typing
`go' must end up calling the shell function `go' and *not* `go.py'
directly. This is how `go' can change the directory in your current shell.

The appropriate function for the *Bash* shell is this:

%s

If you know the appropriate translation for your shell (%s) I'd appreciate
your feedback on that so I can update this script. Please add an issue here:

    http://code.google.com/p/go-tool/issues/list

Thanks!""" % (_indent(_gDriverFromShell["sh"]), shell))

    print("* * *")


# Recipe: query_custom_answers (1.0)
def _query_custom_answers(question, answers, default=None):
    """Ask a question via input() and return the chosen answer.

    @param question {str} Printed on stdout before querying the user.
    @param answers {list} A list of acceptable string answers. Particular
        answers can include '&' before one of its letters to allow a
        single letter to indicate that answer. E.g., ["&yes", "&no",
        "&quit"]. All answer strings should be lowercase.
    @param default {str, optional} A default answer. If no default is
        given, then the user must provide an answer. With a default,
        just hitting <Enter> is sufficient to choose.
    """
    prompt_bits = []
    answer_from_valid_choice = {
        # <valid-choice>: <answer-without-&>
    }
    clean_answers = []
    for answer in answers:
        if '&' in answer and not answer.index('&') == len(answer)-1:
            head, tail = answer.split('&', 1)
            prompt_bits.append(head.lower()+tail.lower().capitalize())
            clean_answer = head+tail
            shortcut = tail[0].lower()
        else:
            prompt_bits.append(answer.lower())
            clean_answer = answer
            shortcut = None
        if default is not None and clean_answer.lower() == default.lower():
            prompt_bits[-1] += " (default)"
        answer_from_valid_choice[clean_answer.lower()] = clean_answer
        if shortcut:
            answer_from_valid_choice[shortcut] = clean_answer
        clean_answers.append(clean_answer.lower())

    # This is what it will look like:
    #   Frob nots the zids? [Yes (default), No, quit] _
    # Possible alternatives:
    #   Frob nots the zids -- Yes, No, quit? [y] _
    #   Frob nots the zids? [*Yes*, No, quit] _
    #   Frob nots the zids? [_Yes_, No, quit] _
    #   Frob nots the zids -- (y)es, (n)o, quit? [y] _
    prompt = " [%s] " % ", ".join(prompt_bits)
    leader = question + prompt
    if len(leader) + max(len(c) for c in answer_from_valid_choice) > 78:
        leader = question + '\n' + prompt.lstrip()
    leader = leader.lstrip()

    admonishment = "*** Please respond with '%s' or '%s'. ***" \
                   % ("', '".join(clean_answers[:-1]), clean_answers[-1])

    while 1:
        sys.stdout.write(leader)
        choice = input().lower()
        if default is not None and choice == '':
            return default
        if choice in answer_from_valid_choice:
            return answer_from_valid_choice[choice]
        sys.stdout.write("\n"+admonishment+"\n\n\n")



# Recipe: indent (0.2.1)
def _indent(string, width=4, skip_first_line=False):
    """_indent(s, [width=4]) -> 'string' indented by 'width' spaces

    The optional "skip_first_line" argument is a boolean (default False)
    indicating if the first line should NOT be indented.
    """
    lines = string.splitlines(1)
    indentstr = ' '*width
    if skip_first_line:
        return indentstr.join(lines)
    return indentstr + indentstr.join(lines)


def _normpath(path):
    normalized_path = normcase(normpath(path))
    if normalized_path.endswith(os.path.sep):
        normalized_path = normalized_path[:-1]
    elif os.path.altsep and normalized_path.endswith(os.path.altsep):
        normalized_path = normalized_path[:-1]
    return normalized_path


def get_home_dir():
    """Get the user's home directory"""
    ret = ''
    try:
        ret = os.environ['HOME']
    except KeyError:
        try:
            ret = os.environ['USERPROFILE']
        except KeyError:
            error('Cannot find home directory.')
    return ret


#---- mainline

def main(argv):
    """Main program entry point"""
    # Must write out a no-op shell script before any error can happen
    # otherwise the script from the previous run could result.
    try:
        shell_script = os.environ[_ENVAR]
    except KeyError:
        setup()
        return 0
    else:
        generate_shell_script(shell_script) # no-op, overwrite old one

    # Parse options
    try:
        shortopts = "hVcpsadlo"
        longopts = ['help', 'version', 'cd', 'print', 'set', 'add-current',
                    'delete', 'list', 'open']
        optlist, args = getopt.getopt(argv[1:], shortopts, longopts)
    except getopt.GetoptError as ex:
        msg = ex.msg
        if ex.opt in ('d', 'dump'):
            msg += ": old -d|--dump option is now -l|--list"
        sys.stderr.write("go: error: %s.\n" % msg)
        sys.stderr.write("See 'go --help'.\n")
        return 1
    action = "cd"
    for opt, _ in optlist:
        if opt in ('-h', '--help'):
            sys.stdout.write(__doc__)
            return 0
        if opt in ('-V', '--version'):
            sys.stdout.write("go %s\n" % __version__)
            return 0
        if opt in ('-c', '--cd'):
            action = "cd"
        elif opt in ('-p', '--print'):
            action = "print"
        elif opt in ('-s', '--set'):
            action = "set"
        elif opt in ('-a', '--add-current'):
            action = "add"
        elif opt in ('-d', '--delete'):
            action = "delete"
        elif opt in ('-l', '--list'):
            action = "list"
        elif opt in ("-o", "--open"):
            action = "open"

    # Parse arguments and do specified action.
    if action == "add":
        if len(args) != 1:
            error("Incorrect number of arguments. argv: %s" % argv)
            return 1
        name, value = args[0], os.getcwd()
        try:
            set_shortcut(name, value)
        except GoError as ex:
            error(str(ex))
            return 1

    elif action == "delete":
        if len(args) != 1:
            error("Incorrect number of arguments. argv: %s" % argv)
            return 1
        name, value = args[0], None
        try:
            set_shortcut(name, value)
        except GoError as ex:
            error(str(ex))
            return 1

    elif action == "set":
        if len(args) != 2:
            error("Incorrect number of arguments. argv: %s" % argv)
            return 1
        name, value = args
        try:
            set_shortcut(name, value)
        except GoError as ex:
            error(str(ex))
            return 1

    elif action == "cd":
        if len(args) > 1:
            error("Incorrect number of arguments. argv: %s" % argv)
            #error("Usage: go [options...] shortcut[/subpath]")
            return 1

        if len(args) == 1:
            path = args[0]
        else:
            path = get_home_dir()

        try:
            generate_shell_script(shell_script, path)
        except KeyError as ex:
            error("Unrecognized shortcut: '%s'" % str(ex))
            return 1
        except GoError as ex:
            error(str(ex))
            return 1

    elif action == "print":
        if len(args) != 1:
            error("Incorrect number of arcuments. argv: %s" % argv)
            return 1

        try:
            path = resolve_path(args[0])
            print(path)
        except GoError as ex:
            error(ex)
            return 1

    elif action == "list":
        if len(args) == 0:
            print_shortcuts(get_shortcut())
        elif len(args) == 1:
            pattern = args[0].lower()
            shortcuts = get_shortcut()
            matching_shortcuts = {}
            for name, value in shortcuts.items():
                if name.lower().find(pattern) != -1:
                    matching_shortcuts[name] = value
            print_shortcuts(matching_shortcuts, "Matching '%s'" % pattern)
        else:
            error("Incorrect number of arguments. argv: %s" % argv)
            return 1

    elif action == "open":

        if len(args) > 1:
            error("Incorrect number of arguments. argv: %s" % argv)
            return 1
        if len(args) == 0:
            args.append(os.getcwd())

        path = args[0]

        try:
            directory = resolve_path(path)
        except GoError as ex:
            error("Error resolving '%s': %s" % (path, ex))
            return 1

        if sys.platform.startswith("win") and not os.environ.get(_FILEMAN_ENV):
            explorer_exe = _find_on_path("explorer.exe")
            if explorer_exe == 0:
                error("Could not find path to Explorer.exe")
                return 1

            os.spawnv(os.P_NOWAIT, explorer_exe, [explorer_exe, '/E,"%s"' % directory])
        else:
            try:
                if sys.platform.startswith('darwin') and not os.environ.get(_FILEMAN_ENV):
                    file_man = '/usr/bin/open'
                else:
                    file_man = os.environ[_FILEMAN_ENV]
                if not os.path.exists(file_man):
                    file_man = _find_on_path(file_man)
                    if file_man == 0:
                        error("Could not find path to '%s'" % file_man)
                        return 1
                os.spawnv(os.P_NOWAIT, file_man, [file_man, directory])

            except KeyError:
                error(
                    "No file manager found.  " +
                    f"Set the {_FILEMAN_ENV} environment variable to set one."
                )

    else:
        error("Internal Error: unknown action: '%s'\n")
        return 1

    return 0

def _find_on_path(prog):
    """Find the file prog on the system PATH.

    Returns the full path to prog or false if not found.
    This only tests if the file name exists, not if it is executable.
    """
    if sys.platform.startswith("win"):
        sep = ';'
    else:
        sep = ':'

    try:
        path = os.environ["PATH"]
    except KeyError:
        error("Could not determine current PATH.")
        return 1

    for folder in path.split(sep):
        fullpath = os.path.join(folder, prog)
        if os.path.isfile(fullpath):
            return fullpath

    return 0


if __name__ == "__main__":
    RETVAL = main(sys.argv)
    sys.exit(RETVAL)
