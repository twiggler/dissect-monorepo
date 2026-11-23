# dissect

Dissect is a digital forensics & incident response framework and toolset that allows you to quickly access and analyse forensic artefacts from various disk and file formats, developed by Fox-IT (part of NCC Group).

For more information, please see [the documentation](https://docs.dissect.tools/).

## What is Dissect?

Dissect is an incident response framework build from various parsers and implementations of file formats. Tying this all together, Dissect allows you to work with tools named `target-query` and `target-shell` to quickly gain access to forensic artefacts, such as Runkeys, Prefetch files, and Windows Event Logs, just to name a few!

**Singular approach**

And the best thing: all in a singular way, regardless of underlying container (E01, VMDK, QCoW), filesystem (NTFS, ExtFS, FFS), or Operating System (Windows, Linux, ESXi) structure / combination. You no longer have to bother extracting files from your forensic container, mount them (in case of VMDKs and such), retrieve the MFT, and parse it using a separate tool, to finally create a timeline to analyse. This is all handled under the hood by Dissect in a user-friendly manner.

If we take the example above, you can start analysing parsed MFT entries by just using a command like `target-query -f mft <PATH_TO_YOUR_IMAGE>`!

**Create a lightweight container using Acquire**

Dissect also provides you with a tool called `acquire`. You can deploy this tool on endpoint(s) to create a lightweight container of these machine(s). What is convenient as well, is that you can deploy `acquire` on a hypervisor to quickly create lightweight containers of all the (running) virtual machines on there! All without having to worry about file-locks. These lightweight containers can then be analysed using the tools like `target-query` and `target-shell`, but feel free to use other tools as well.

**A modular setup**

Dissect is made with a modular approach in mind. This means that each individual project can be used on its own (or in combination) to create a completely new tool for your engagement or future use!

**Try it out now!**

Interested in trying it out for yourself? You can simply `pip install dissect` and start using the `target-*` tooling right away. Or you can use the interactive playground at https://try.dissect.tools to try Dissect in your browser.

Don’t know where to start? Check out the [introduction page](https://docs.dissect.tools/en/latest/usage/introduction.html).

Want to get a detailed overview? Check out the [overview page](https://docs.dissect.tools/en/latest/overview/).

Want to read everything? Check out the [documentation](https://docs.dissect.tools).

## Community

Join our [Discord server](https://discord.gg/tS48YbzXN7) to connect with the community and get support.

## Projects

Dissect consists out of several individual projects, all of which are housed in this monorepo. 
Each project is self-contained and can invidiually be installed.

| Project                                               | Description                                                               |
| ----------------------------------------------------- | ------------------------------------------------------------------------- |
| [dissect.apfs](/projects/dissect.apfs)                | APFS file system                                                          |
| [dissect.archive](/projects/dissect.archive)          | Various archive and backup formats (VBK, WIM, VMA, XVA)                   |
| [dissect.btrfs](/projects/dissect.btrfs)              | Btrfs file system                                                         |
| [dissect.cim](/projects/dissect.cim)                  | Windows Common Information Model (CIM) database                           |
| [dissect.clfs](/projects/dissect.clfs)                | Common Log File System (CLFS)                                             |
| [dissect.cramfs](/projects/dissect.cramfs)            | Compressed ROM/RAM file system (cramfs)                                   |
| [dissect.cstruct](/projects/dissect.cstruct)          | Parse C-like structure definitions                                        |
| [dissect.database](/projects/dissect.database)        | Various database formats (SQLite, ESE, Bbolt, Berkeley)                   |
| [dissect.etl](/projects/dissect.etl)                  | Windows Event Trace Log (ETL)                                             |
| [dissect.eventlog](/projects/dissect.eventlog)        | Windows EVT, EVTX and WEVT logs                                           |
| [dissect.evidence](/projects/dissect.evidence)        | Various evidence formats (AD1, EWF1, AFF4)                                |
| [dissect.executable](/projects/dissect.executable)    | Various executable formats (PE, ELF)                                      |
| [dissect.extfs](/projects/dissect.extfs)              | ext4 file system                                                          |
| [dissect.fat](/projects/dissect.fat)                  | FAT12, FAT16, FAT32, ExFAT and XFAT file systems                          |
| [dissect.ffs](/projects/dissect.ffs)                  | FFS file system                                                           |
| [dissect.fve](/projects/dissect.fve)                  | Various full volume encryption formats (BitLocker, LUKS, VeraCrypt)       |
| [dissect.hypervisor](/projects/dissect.hypervisor)    | Various formats related to hypervisors (virtual disks, descriptor files)  |
| [dissect.jffs](/projects/dissect.jffs)                | JFFS2 file system                                                         |
| [dissect.ntfs](/projects/dissect.ntfs)                | NTFS file system                                                          |
| [dissect.ole](/projects/dissect.ole)                  | Object Linking & Embedding (OLE) format                                   |
| [dissect.qnxfs](/projects/dissect.qnxfs)              | QNX4 and QNX6 file system                                                 |
| [dissect.regf](/projects/dissect.regf)                | Windows registry file format                                              |
| [dissect.shellitem](/projects/dissect.shellitem)      | Windows shell item formats                                                |
| [dissect.squashfs](/projects/dissect.squashfs)        | SquashFS file system                                                      |
| [dissect.target](/projects/dissect.target)            | The Dissect module tying all other Dissect modules together               |
| [dissect.thumbcache](/projects/dissect.thumbcache)    | Windows thumbcache format                                                 |
| [dissect.util](/projects/dissect.util)                | Various utilities (compression, hashes, timestamps, streams)              |
| [dissect.vmfs](/projects/dissect.vmfs)                | VMFS5 and VMFS6 file system                                               |
| [dissect.volume](/projects/dissect.volume)            | Various volume, partition and RAID schemes (LVM2, DDF, MD, and more)      |
| [dissect.xfs](/projects/dissect.xfs)                  | XFS file system                                                           |

### Related

These projects are closely related to Dissect, but not installed when you install `dissect`.

| Project                                               | Description                                                               |
| ----------------------------------------------------- | ------------------------------------------------------------------------- |
| [acquire](https://github.com/fox-it/acquire)          | Lightweight forensic data collection from disk images or a live system    |
| [flow.record](https://github.com/fox-it/flow.record)  | Data recordization library                                                |

## Requirements

This project is part of the Dissect framework and requires Python.

Information on the supported Python versions can be found in the Getting Started section of [the documentation](https://docs.dissect.tools/en/latest/index.html#getting-started).

## Installation

`dissect` is available on [PyPI](https://pypi.org/project/dissect/).

```bash
pip install dissect
```

## Development instructions

This project uses `just` for executing common tasks. For example, to run unit tests, run:

```bash
# Test all projects
just test-all
# Only test a specific project
just test dissect.cstruct
```

And for linting, you'd run:

```bash
just lint
# If you want Ruff to auto-apply linting suggestions
just fix
```

For a more elaborate explanation on how to build and test the project, please see [the
documentation](https://docs.dissect.tools/en/latest/contributing/tooling.html).

## Contributing

The Dissect project encourages any contribution to the codebase. To make your contribution fit into the project, please
refer to [the development guide](https://docs.dissect.tools/en/latest/contributing/developing.html).

## Copyright and license

Dissect is released as open source by Fox-IT (<https://www.fox-it.com>) part of NCC Group Plc
(<https://www.nccgroup.com>).

Developed by the Dissect Team (<dissect@fox-it.com>) and made available at <https://github.com/fox-it/dissect>.

License terms: mixed AGPL3 (<https://www.gnu.org/licenses/agpl-3.0.html>) and Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0). 
For more information, see the LICENSE file of each project.
