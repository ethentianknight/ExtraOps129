Extra Ops 129 - Steam Deck

INSTALL

1. Switch the Steam Deck to Desktop Mode.
2. In Steam, open Peace Walker > Properties > Installed Files > Browse.
3. Extract the Steam Deck ZIP into the MGS_PW folder.

The folders must look like this:

MGS_PW/
  Extra Ops 129/
  mgspw/

4. Open the Extra Ops 129 folder in Dolphin.
5. Right-click an empty area and choose Open Terminal.
6. Run:

bash deck/setup.sh

7. Choose an installation mode:

1: Models
2: Four-player co-op
3: Models and four-player co-op

8. In Steam, open Peace Walker > Properties > General.
9. Enter this in Launch Options:

WINEDLLOVERRIDES="winmm=n,b" %command%

RUN

Return to Gaming Mode and start Peace Walker normally through Steam.

The Steam Deck runtime starts with the game. It applies the installed model and co-op runtime changes and the network stability patch automatically. Do not run the Windows EXE or CMD files.

Runtime status is written to:

mgspw/eo129_deck.log

MODEL CONFIG

Edit character_config.txt before starting Peace Walker. Save the file and restart the game to apply changes. Reinstallation is not required for config changes.

UPDATE

1. Close Peace Walker.
2. Run bash deck/setup.sh from the installed Extra Ops 129 folder.
3. Choose option 4 to uninstall the current version.
4. Extract the new Steam Deck package over the Extra Ops 129 folder.
5. Run bash deck/setup.sh again and choose option 1, 2, or 3.

UNINSTALL

1. Close Peace Walker.
2. Run bash deck/setup.sh.
3. Choose option 4.
4. Remove the WINEDLLOVERRIDES launch option from Steam.

SAVE RESTORE

Option 5 uninstalls the mod and restores a save backup. Option 6 restores a save backup without uninstalling.

Before restoring a save, disable Steam Cloud for Peace Walker and exit Steam completely. Restart Steam after the restore finishes. If Steam reports a conflict, keep the local files.

FILES

The installer modifies:

mgspw/MLG/disc0_rel/002aba34.DAT
mgspw/MLG/disc0_rel/002aba34.KEY
mgspw/MLG/disc0_rel/009645fa.PDT

The Steam Deck runtime installs:

mgspw/winmm.dll

Original game archives are stored in:

Extra Ops 129/backups/

Save backups are stored in:

Extra Ops 129/save-backups/

REQUIREMENTS

SteamOS x86_64
Python 3.8 or newer
Metal Gear Solid: Peace Walker Steam build 25052315

The installer stops if mgspw/winmm.dll already exists. Remove the conflicting DLL mod before installing Extra Ops 129.
