# Blokius reference engine

`blokius-wip1.zip` is the unchanged `Blokius - sprite manager wip 1.zip` from John's original project folder. The playable build extracts it into a temporary directory, verifies its prebuilt reference, and applies the current game's source and artwork.

Keeping the archive intact preserves the timing baseline and the bundled engine and converter sources. The active editable graphics are in `art`. The assembly changes for the current game are in `game`, `tests`, and the integration tools.

The Windows compressor and standard Z80 decoder in `zx0` come from [Einar Saukas's ZX0 repository](https://github.com/einar-saukas/ZX0/tree/ecde3a2ae05061fe06469ed46df81a33b7de7d86) at revision `ecde3a2`. The included license covers redistribution. The decoder credits Einar Saukas and Urusergi.
