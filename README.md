# Extra Ops 129

Character models and four-player co-op for Metal Gear Solid: Peace Walker.

## Modified files

- `mgspw\MLG\disc0_rel\002aba34.DAT`
- `mgspw\MLG\disc0_rel\002aba34.KEY`
- `mgspw\MLG\disc0_rel\009645fa.PDT`

## Save backups

- `Extra Ops 129\save-backups\`

## Setup

1. Restore older EO129 or Co-op 4 installations with their original installer.
2. In Steam, select Peace Walker > Manage > Browse local files.
3. Copy the complete `Extra Ops 129` folder beside the `mgspw` folder.
4. Close Peace Walker and run `Setup Extra Ops 129.cmd`.
5. Choose an installation mode:
   - `1`: Install models
   - `2`: Install four-player co-op
   - `3`: Install models and four-player co-op

## Play

Run `Play Extra Ops 129.cmd` for every modded session. Start Peace Walker through its launcher and wait for the active message before selecting a mission. The helper can close after applying the runtime hooks. Runtime changes disappear when the game exits.

After Peace Walker proper has opened, run `Patch PW Networking Protocol.exe`. Wait for it to report that the patch was applied, then close it. Run it once for every game session. The network patch changes memory only and does not edit game files or saves.

Windows Defender and other antivirus software may flag the included executables because they modify the running game. The network patch executable is the most likely to be flagged because it allocates and writes executable process memory and starts a remote thread to configure Steam Networking timeouts. Source and technical details are included in `NETWORK_PROTOCOL.md` and `source/network_protocol.py`.

## Models

Edit `character_config.txt` before starting the game. `0` leaves an outfit unchanged. See `Roster.txt` for the available characters.

Starting the game directly through Steam does not apply model replacements.

## Four-player co-op

Missions originally capped at two players are changed to four players, except Main Op 20: Torture Chamber Escape. Original one-player and four-player missions are unchanged.

Every player needs the same mod mode installed and must start the game through `Play Extra Ops 129.cmd`.

The network protocol patch remains compatible with unpatched players, but each player should run it because it repairs that player's local connection handling.

Players 3 and 4 reuse placements 1 and 2 when a room only provides two spawn placements. Room transitions, cutscenes, special scripts, and every individual mission have not all been tested.

## Uninstall and save restoration

Run `Setup Extra Ops 129.cmd` and choose:

- `4`: Uninstall all
- `5`: Uninstall all and restore save
- `6`: Restore save only

Uninstall restores all three original archives regardless of the installed mode.

After option 4 or 5, launch the vanilla game directly through Steam. To use the mod again, run Setup, install option 1, 2, or 3, and then use `Play Extra Ops 129.cmd`.

Before using option 5 or 6, disable Steam Cloud for Peace Walker in Steam's game properties. Exit Steam completely, run the restore, and restart Steam after it finishes. If Steam reports a conflict, keep the local files.

The installer preserves the current saves, verifies the restored snapshot after replacement, and refreshes its local timestamps.

## Manual backups

- `mgspw\MLG\disc0_rel\002aba34.DAT`
- `mgspw\MLG\disc0_rel\002aba34.KEY`
- `mgspw\MLG\disc0_rel\009645fa.PDT`
- `mgspw_savedata_win\`

The installer stores verified original archives under `Extra Ops 129\backups\`. Keep the installed folder and do not share `backups` or `save-backups`.

## Requirements

- Metal Gear Solid: Peace Walker Steam build `25052315`
- Windows x64
- No Python installation required for the release package

Installation refuses unsupported or previously modified archives.

## Troubleshooting

`No installation record was found` means Setup was not completed from the current `Extra Ops 129` folder, or the folder was moved after installation. Keep the folder in place, run `Setup Extra Ops 129.cmd`, and choose option 1, 2, or 3 before Play.

## Building

Use Python 3.12 x64:

```text
python -m pip install -r requirements.txt
python build.py
```

Release files are written to `dist\`.

Build the Steam Deck package on Windows with the Visual Studio C++ tools installed:

```text
python build_deck.py
```
